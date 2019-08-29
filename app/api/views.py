from urllib.parse import urljoin

from rest_framework.response import Response
from rest_framework import status
from rest_framework import exceptions
from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.generics import get_object_or_404
from rest_framework_extensions.mixins import NestedViewSetMixin
from rest_framework.renderers import JSONRenderer, TemplateHTMLRenderer
from rest_framework.decorators import action
from django.db import transaction, connection

from core.wallet import *
from core.permissions import *
from core.sync2async import run_async
from .serializers import *
from .models import Wallet


WALLET_AGENT_TIMEOUT = settings.INDY['WALLET_SETTINGS']['TIMEOUTS']['AGENT_REQUEST']


class AdminWalletViewSet(viewsets.mixins.RetrieveModelMixin,
                         viewsets.mixins.CreateModelMixin,
                         viewsets.mixins.DestroyModelMixin,
                         viewsets.mixins.ListModelMixin,
                         viewsets.GenericViewSet):
    """Operate with wallets"""
    permission_classes = [IsNonAnonymousUser]
    renderer_classes = [JSONRenderer]
    lookup_field = 'uid'
    queryset = Wallet.objects
    wallet_creation_timeout = settings.INDY['WALLET_SETTINGS']['TIMEOUTS']['CREATE_DELETE']

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(owner=self.request.user)

    def get_serializer_class(self):
        if self.action in ['retrieve', 'list']:
            return WalletRetrieveSerializer
        elif self.action in ['open', 'close', 'destroy']:
            return WalletAccessSerializer
        elif self.action == 'create':
            return WalletCreateSerializer
        elif self.action == 'is_open':
            return EmptySerializer
        else:
            raise NotImplemented()

    def list(self, request, *args, **kwargs):
        wallets = self.get_queryset().all()
        serializer = WalletRetrieveSerializer(
            instance=[self.__to_dict(x) for x in wallets],
            many=True
        )
        return Response(data=serializer.data)

    def retrieve(self, request, *args, **kwargs):
        wallet = self.get_object()
        serializer = WalletRetrieveSerializer(instance=self.__to_dict(wallet))
        return Response(data=serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = WalletCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credentials = serializer.create(serializer.validated_data)
        if Wallet.objects.filter(uid=credentials['uid']).exists():
            raise exceptions.ValidationError("Wallet with same UID already exists")
        conn = WalletConnection(agent_name=credentials['uid'], pass_phrase=credentials['pass_phrase'])
        try:
            with transaction.atomic():
                wallet = Wallet.objects.create(uid=credentials['uid'], owner=request.user)
            run_async(conn.create(), timeout=self.wallet_creation_timeout)
        except BaseWalletException as e:
            raise exceptions.ValidationError(e.error_message)
        else:
            data = self.__to_dict(wallet)
            data.update(credentials)
            serializer = WalletCreateSerializer(instance=data)
            return Response(data=serializer.data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        wallet = self.get_object()
        serializer = WalletAccessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credentials = serializer.create(serializer.validated_data)
        conn = WalletConnection(agent_name=wallet.uid, pass_phrase=credentials['pass_phrase'])
        try:
            with transaction.atomic():
                wallet.delete()
                try:
                    run_async(WalletAgent.close(
                        agent_name=wallet.uid,
                        pass_phrase=credentials['pass_phrase']
                    ), timeout=self.wallet_creation_timeout)
                except BaseWalletException:
                    pass
                try:
                    run_async(conn.delete(), timeout=self.wallet_creation_timeout)
                except BaseWalletException:
                    db_name = WalletConnection.make_wallet_address(wallet.uid)
                    with connection.cursor() as cursor:
                        cursor.execute("DROP DATABASE '%s'" % db_name)
        except BaseWalletException as e:
            raise exceptions.ValidationError(e.error_message)
        else:
            return Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=['POST'], detail=True)
    def open(self, request, *args, **kwargs):
        wallet = self.get_object()
        serializer = WalletAccessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credentials = serializer.create(serializer.validated_data)
        try:
            run_async(WalletAgent.ensure_agent_is_open(agent_name=wallet.uid, pass_phrase=credentials['pass_phrase']))
        except BaseWalletException as e:
            if isinstance(e, AgentTimeOutError):
                logging.exception('Runtime error!')
                raise
            else:
                raise exceptions.ValidationError(e.error_message)
        else:
            return Response(status=status.HTTP_200_OK)

    @action(methods=['POST'], detail=True)
    def close(self, request, *args, **kwargs):
        wallet = self.get_object()
        serializer = WalletAccessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credentials = serializer.create(serializer.validated_data)
        try:
            run_async(WalletAgent.close(agent_name=wallet.uid, pass_phrase=credentials['pass_phrase']))
        except BaseWalletException as e:
            if isinstance(e, AgentTimeOutError):
                pass
            else:
                raise exceptions.ValidationError(e.error_message)
        return Response(status=status.HTTP_200_OK)

    @action(methods=['GET'], detail=True)
    def is_open(self, request, *args, **kwargs):
        wallet = self.get_object()
        value = run_async(WalletAgent.is_open(agent_name=wallet.uid))
        return Response(status=status.HTTP_200_OK, data=dict(is_open=value))

    @staticmethod
    def __to_dict(instance: Wallet):
        return dict(uid=instance.uid)


class PairwiseViewSet(NestedViewSetMixin,
                      viewsets.GenericViewSet):
    """Pairwise list discovering"""
    permission_classes = [IsNonAnonymousUser]
    renderer_classes = [JSONRenderer]
    serializer_class = WalletAccessSerializer

    def get_serializer_class(self):
        if self.action == 'get_metadata':
            return DIDAccessSerializer
        else:
            return super().get_serializer_class()

    @action(methods=['POST'], detail=False)
    def all(self, request, *args, **kwargs):
        wallet = self.get_wallet()
        serializer = WalletAccessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credentials = serializer.create(serializer.validated_data)
        ret = run_async(
            WalletAgent.list_pairwise(
                agent_name=wallet.uid,
                pass_phrase=credentials['pass_phrase']
            ),
            timeout=WALLET_AGENT_TIMEOUT
        )
        return Response(data=ret)

    @action(methods=['POST'], detail=False)
    def get_metadata(self, request, *args, **kwargs):
        wallet = self.get_wallet()
        serializer = DIDAccessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credentials = serializer.create(serializer.validated_data)
        try:
            ret = run_async(
                WalletAgent.get_pairwise(
                    agent_name=wallet.uid,
                    pass_phrase=credentials['pass_phrase'],
                    their_did=credentials['their_did']
                ),
                timeout=WALLET_AGENT_TIMEOUT
            )
        except WalletItemNotFound as e:
            raise exceptions.ValidationError(detail=e.error_message)
        return Response(data=ret)

    def get_wallet(self):
        if 'wallet' in self.get_parents_query_dict():
            wallet_uid = self.get_parents_query_dict()['wallet']
            return get_object_or_404(Wallet.objects, uid=wallet_uid, owner=self.request.user)
        else:
            raise exceptions.NotFound()


class WalletState(APIView):
    template_name = 'wallet_state.html'
    renderer_classes = [TemplateHTMLRenderer]

    def get(self, request):
        context = dict()
        host = request.META['HTTP_HOST']
        schema = 'wss' if request.is_secure() else 'ws'
        context['websocket'] = '%s:%s/ws/wallets/status/' % (schema, host)
        return Response(data=context)
