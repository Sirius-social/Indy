from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from .models import Endpoint


class EndpointSerializer(serializers.ModelSerializer):

    uid = serializers.CharField(max_length=128, read_only=True)

    class Meta:
        model = Endpoint
        fields = ('uid', 'url')
        read_only_fields = ('uid', 'url')


def validate_feature(value):
    expected = [InvitationSerializer.FEATURE_0023_ARIES_RFC, InvitationSerializer.FEATURE_CUSTOM_CONN]
    if value not in expected:
        raise ValidationError('Expected values: [%s]' % ','.join(expected))


class InvitationSerializer(serializers.Serializer):

    FEATURE_0023_ARIES_RFC = 'aries_rfcs_0023'
    FEATURE_CUSTOM_CONN = 'connection'

    url = serializers.CharField(max_length=2083, required=False)
    feature = serializers.CharField(
        max_length=36,
        default=FEATURE_0023_ARIES_RFC,
        validators=[validate_feature],
        help_text='Available values: [%s]' % ','.join([FEATURE_0023_ARIES_RFC, FEATURE_CUSTOM_CONN])
    )

    def create(self, validated_data):
        return dict(validated_data)

    def update(self, instance, validated_data):
        instance['url'] = validated_data.get('url', None)
        instance['feature'] = validated_data.get('feature')


class CreateInvitationSerializer(InvitationSerializer):

    pass_phrase = serializers.CharField(max_length=512, required=True)

    def update(self, instance, validated_data):
        instance['pass_phrase'] = validated_data.get('pass_phrase')
