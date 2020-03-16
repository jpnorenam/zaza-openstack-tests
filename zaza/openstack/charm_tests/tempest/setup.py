# Copyright 2020 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Code for configuring tempest."""
import urllib.parse
import os
import shutil
import subprocess

import zaza.model
import zaza.utilities.deployment_env as deployment_env
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.charm_tests.glance.setup as glance_setup
import zaza.openstack.charm_tests.tempest.templates.tempest_v2 as tempest_v2
import zaza.openstack.charm_tests.tempest.templates.tempest_v3 as tempest_v3
import zaza.openstack.charm_tests.tempest.templates.accounts as accounts
import tempest.cmd.main

import keystoneauth1
import novaclient

SETUP_ENV_VARS = [
    'OS_TEST_GATEWAY',
    'OS_TEST_CIDR_EXT',
    'OS_TEST_FIP_RANGE',
    'OS_TEST_NAMESERVER',
    'OS_TEST_CIDR_PRIV',
    'OS_TEST_SWIFT_IP',
]
TEMPEST_FLAVOR_NAME = 'm1.tempest'
TEMPEST_ALT_FLAVOR_NAME = 'm2.tempest'
TEMPEST_CIRROS_ALT_IMAGE_NAME = 'cirros_alt'


def get_app_access_ip(application_name):
    try:
        app_config = zaza.model.get_application_config(application_name)
    except KeyError:
        return ''
    vip = app_config.get("vip").get("value")
    if vip:
        ip = vip
    else:
        unit = zaza.model.get_units(application_name)[0]
        ip = unit.public_address
    return ip


def add_application_ips(ctxt):
    ctxt['keystone'] = get_app_access_ip('keystone')
    ctxt['dashboard'] = get_app_access_ip('openstack-dashboard')
    ctxt['ncc'] = get_app_access_ip('nova-cloud-controller')


def add_nova_config(ctxt, keystone_session):
    nova_client = openstack_utils.get_nova_session_client(
        keystone_session)
    for flavor in nova_client.flavors.list():
        if flavor.name == TEMPEST_FLAVOR_NAME:
            ctxt['flavor_ref'] = flavor.id
        if flavor.name == TEMPEST_ALT_FLAVOR_NAME:
            ctxt['flavor_ref_alt'] = flavor.id


def add_neutron_config(ctxt, keystone_session):
    neutron_client = openstack_utils.get_neutron_session_client(
        keystone_session)
    for net in neutron_client.list_networks()['networks']:
        if net['name'] == 'ext_net':
            ctxt['ext_net'] = net['id']
            break
    for router in neutron_client.list_routers()['routers']:
        if router['name'] == 'provider-router':
            ctxt['provider_router_id'] = router['id']
            break


def add_glance_config(ctxt, keystone_session):
    glance_client = openstack_utils.get_glance_session_client(
        keystone_session)
    image = openstack_utils.get_images_by_name(
        glance_client, glance_setup.CIRROS_IMAGE_NAME)
    image_alt = openstack_utils.get_images_by_name(
        glance_client, TEMPEST_CIRROS_ALT_IMAGE_NAME)
    if image:
        ctxt['image_id'] = image[0].id
    if image_alt:
        ctxt['image_alt_id'] = image_alt[0].id


def add_keystone_config(ctxt, keystone_session):
    keystone_client = openstack_utils.get_keystone_session_client(
        keystone_session)
    for domain in keystone_client.domains.list():
        if domain.name == 'admin_domain':
            ctxt['default_domain_id'] = domain.id
            break


def add_environment_var_config(ctxt):
    deploy_env = deployment_env.get_deployment_context()
    for var in SETUP_ENV_VARS:
        value = deploy_env.get(var)
        if value:
            ctxt[var.lower()] = value
        else:
            raise ValueError(
                ("Environment variables {} must all be set to run this"
                 " test").format(', '.join(SETUP_ENV_VARS)))


def add_access_protocol(ctxt):
    overcloud_auth = openstack_utils.get_overcloud_auth()
    ctxt['proto'] = urllib.parse.urlparse(overcloud_auth['OS_AUTH_URL']).scheme
    ctxt['admin_username'] = overcloud_auth['OS_USERNAME']
    ctxt['admin_password'] = overcloud_auth['OS_PASSWORD']
    if overcloud_auth['API_VERSION'] == 3:
        ctxt['admin_project_name'] = overcloud_auth['OS_PROJECT_NAME']
        ctxt['admin_domain_name'] = overcloud_auth['OS_DOMAIN_NAME']
        ctxt['default_credentials_domain_name'] = overcloud_auth[
             'OS_PROJECT_DOMAIN_NAME']
    elif overcloud_auth['API_VERSION'] == 2:
        #ctxt['admin_tenant_name'] = overcloud_auth['OS_TENANT_NAME']
        pass


def get_tempest_context():
    keystone_session = openstack_utils.get_overcloud_keystone_session()
    ctxt = {}
    #add_application_ips(ctxt)
    #add_nova_config(ctxt, keystone_session)
    #add_neutron_config(ctxt, keystone_session)
    #add_glance_config(ctxt, keystone_session)
    #add_keystone_config(ctxt, keystone_session)
    #add_environment_var_config(ctxt)
    #add_access_protocol(ctxt)
    return ctxt


def render_tempest_config(target_file, ctxt, tempest_template):
    with open(target_file, 'w') as f:
        f.write(tempest_template.file_contents.format(**ctxt))


def setup_tempest(tempest_template, accounts_template):
    config_dir = '.tempest'
    config_etc_dir = os.path.join(config_dir, 'etc')
    config_etc_tempest = os.path.join(config_etc_dir, 'tempest.conf')
    config_workspace_yaml = os.path.join(config_dir, 'workspace.yaml')
    workspace_name = 'workspace'
    workspace_dir = os.path.join(config_dir, workspace_name)
    workspace_etc_dir = os.path.join(workspace_dir, 'etc')
    workspace_etc_accounts = os.path.join(workspace_etc_dir, 'accounts.yaml')
    workspace_etc_tempest = os.path.join(workspace_etc_dir, 'tempest.conf')
    the_app = tempest.cmd.main.Main()

    # note sure this is needed or not
    if not os.path.isdir(config_dir):
        os.mkdir(config_dir)
        os.mkdir(config_etc_dir)
    render_tempest_config(
        config_etc_tempest,
        get_tempest_context(),
        tempest_template)
    tempest_options = ['init', '--workspace-path', config_workspace_yaml,
                       '--name', workspace_name, workspace_dir]
    print(tempest_options)
    _exec_tempest = the_app.run(tempest_options)
    # This was mising /etc/tempest/ and just going to /etc/
    render_tempest_config(
        workspace_etc_tempest,
        get_tempest_context(),
        tempest_template)
    render_tempest_config(
        workspace_etc_accounts,
        get_tempest_context(),
        accounts_template)


def render_tempest_config_keystone_v2():
    setup_tempest(tempest_v2, accounts)


def render_tempest_config_keystone_v3():
    setup_tempest(tempest_v3, accounts)


def add_cirros_alt_image():
    """Add a cirros image to the current deployment.

    :param glance: Authenticated glanceclient
    :type glance: glanceclient.Client
    :param image_name: Label for the image in glance
    :type image_name: str
    """
    image_url = openstack_utils.find_cirros_image(arch='x86_64')
    glance_setup.add_image(
        image_url,
        glance_client=None,
        image_name=TEMPEST_CIRROS_ALT_IMAGE_NAME)


def add_tempest_flavors():
    keystone_session = openstack_utils.get_overcloud_keystone_session()
    nova_client = openstack_utils.get_nova_session_client(
        keystone_session)
    try:
        nova_client.flavors.create(
            name=TEMPEST_FLAVOR_NAME,
            ram=256,
            vcpus=1,
            disk=1)
    except novaclient.exceptions.Conflict:
        pass
    try:
        nova_client.flavors.create(
            name=TEMPEST_ALT_FLAVOR_NAME,
            ram=512,
            vcpus=1,
            disk=1)
    except novaclient.exceptions.Conflict:
        pass


def add_tempest_roles():
    keystone_session = openstack_utils.get_overcloud_keystone_session()
    keystone_client = openstack_utils.get_keystone_session_client(
        keystone_session)
    for role_name in ['Member', 'ResellerAdmin']:
        try:
            keystone_client.roles.create(role_name)
        except keystoneauth1.exceptions.http.Conflict:
            pass

