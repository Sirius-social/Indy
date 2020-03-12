import json
from time import sleep
from ctypes import cdll
from .utils import ProvisionConfig, Invitation, file_ext

from vcx.state import State
from vcx.api.utils import vcx_agent_provision
from vcx.api.connection import Connection
from vcx.api.vcx_init import vcx_init_with_config


async def alice_create_connection(alice: ProvisionConfig, invitation: Invitation=None):
    payment_plugin = cdll.LoadLibrary('libnullpay' + file_ext())
    payment_plugin.nullpay_init()

    config = await vcx_agent_provision(str(alice))
    config = json.loads(config)
    # Set some additional configuration options specific to alice
    config['institution_name'] = 'alice'
    config['institution_logo_url'] = 'http://robohash.org/456'
    config['genesis_path'] = '/ci/test_local_pool_transactions_genesis'
    config = json.dumps(config, indent=2, sort_keys=True)
    print('======= Alice config ========')
    print(config)
    print('=============================')
    await vcx_init_with_config(config)
    details = str(invitation)
    connection_to_faber = await Connection.create_with_details(invitation.label, details)
    await connection_to_faber.connect('{"use_public_did": true}')
    connection_state = await connection_to_faber.update_state()
    while connection_state != State.Accepted:
        sleep(2)
        await connection_to_faber.update_state()
        connection_state = await connection_to_faber.get_state()
        pass
    print('!!!!!!')
    pass