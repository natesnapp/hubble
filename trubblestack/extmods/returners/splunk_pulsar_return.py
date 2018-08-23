# -*- encoding: utf-8 -*-
'''
TrubbleStack Pulsar-to-Splunk returner

Deliver TrubbleStack Pulsar event data into Splunk using the HTTP
event collector. Required config/pillar settings:

.. code-block:: yaml

    trubblestack:
      returner:
        splunk:
          - token: XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
            indexer: splunk-indexer.domain.tld
            index: trubble
            sourcetype_pulsar: trubble_fim

You can also add a `custom_fields` argument which is a list of keys to add to
events with using the results of config.get(<custom_field>). These new keys
will be prefixed with 'custom_' to prevent conflicts. The values of these keys
should be strings or lists (will be sent as CSV string), do not choose grains
or pillar values with complex values or they will be skipped.

Additionally, you can define a fallback_indexer which will be used if a default
gateway is not defined.

.. code-block:: yaml

    trubblestack:
      returner:
        splunk:
          - token: XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
            indexer: splunk-indexer.domain.tld
            index: trubble
            sourcetype_pulsar: trubble_fim
            fallback_indexer: splunk-indexer.loc.domain.tld
            custom_fields:
              - site
              - product_group
'''
import socket

# Imports for http event forwarder
import requests
import json
import os
import time
from collections import defaultdict
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import logging

_max_content_bytes = 100000
http_event_collector_debug = False
RETRY = False

log = logging.getLogger(__name__)


def returner(ret):
    try:
        if isinstance(ret, dict) and not ret.get('return'):
            # Empty single return, let's not do any setup or anything
            return

        opts_list = _get_options()

        for opts in opts_list:
            logging.debug('Options: %s' % json.dumps(opts))
            http_event_collector_key = opts['token']
            http_event_collector_host = opts['indexer']
            http_event_collector_port = opts['port']
            hec_ssl = opts['http_event_server_ssl']
            proxy = opts['proxy']
            timeout = opts['timeout']
            custom_fields = opts['custom_fields']
            http_event_collector_ssl_verify = opts['http_event_collector_ssl_verify']

            # Set up the fields to be extracted at index time. The field values must be strings.
            # Note that these fields will also still be available in the event data
            index_extracted_fields = []
            try:
                index_extracted_fields.extend(__opts__.get('splunk_index_extracted_fields', []))
            except TypeError:
                pass

            # Set up the collector
            hec = http_event_collector(http_event_collector_key, http_event_collector_host,
                                       http_event_port=http_event_collector_port, http_event_server_ssl=hec_ssl,
                                       http_event_collector_ssl_verify=http_event_collector_ssl_verify,
                                       proxy=proxy, timeout=timeout)
            # Check whether or not data is batched:
            if isinstance(ret, dict):  # Batching is disabled
                data = [ret]
            else:
                data = ret
            # Sometimes there are duplicate events in the list. Dedup them:
            data = _dedupList(data)
            minion_id = __opts__['id']
            jid = ret['jid']
            global RETRY
            RETRY = ret['retry']
            fqdn = __grains__['fqdn']
            # Sometimes fqdn is blank. If it is, replace it with minion_id
            fqdn = fqdn if fqdn else minion_id
            master = __grains__['master']
            try:
                fqdn_ip4 = __grains__.get('local_ip4')
                if not fqdn_ip4:
                    fqdn_ip4 = __grains__['fqdn_ip4'][0]
            except IndexError:
                try:
                    fqdn_ip4 = __grains__['ipv4'][0]
                except IndexError:
                    raise Exception('No ipv4 grains found. Is net-tools installed?')
            if fqdn_ip4.startswith('127.'):
                for ip4_addr in __grains__['ipv4']:
                    if ip4_addr and not ip4_addr.startswith('127.'):
                        fqdn_ip4 = ip4_addr
                        break
            local_fqdn = __grains__.get('local_fqdn', __grains__['fqdn'])

            # Sometimes fqdn reports a value of localhost. If that happens, try another method.
            bad_fqdns = ['localhost', 'localhost.localdomain', 'localhost6.localdomain6']
            if fqdn in bad_fqdns:
                new_fqdn = socket.gethostname()
                if '.' not in new_fqdn or new_fqdn in bad_fqdns:
                    new_fqdn = fqdn_ip4
                fqdn = new_fqdn

            # Get cloud details
            cloud_details = __grains__.get('cloud_details', {})

            alerts = []
            for item in data:
                events = item['return']
                if not isinstance(events, list):
                    events = [events]
                alerts.extend(events)

            for alert in alerts:
                event = {}
                payload = {}
                if('change' in alert):  # Linux, normal pulsar
                    # The second half of the change will be '|IN_ISDIR' for directories
                    change = alert['change'].split('|')[0]
                    # Skip the IN_IGNORED events
                    if change == 'IN_IGNORED':
                        continue
                    if len(alert['change'].split('|')) == 2:
                        object_type = 'directory'
                    else:
                        object_type = 'file'

                    actions = defaultdict(lambda: 'unknown')
                    actions['IN_ACCESS'] = 'read'
                    actions['IN_ATTRIB'] = 'acl_modified'
                    actions['IN_CLOSE_NOWRITE'] = 'read'
                    actions['IN_CLOSE_WRITE'] = 'read'
                    actions['IN_CREATE'] = 'created'
                    actions['IN_DELETE'] = 'deleted'
                    actions['IN_DELETE_SELF'] = 'deleted'
                    actions['IN_MODIFY'] = 'modified'
                    actions['IN_MOVE_SELF'] = 'modified'
                    actions['IN_MOVED_FROM'] = 'modified'
                    actions['IN_MOVED_TO'] = 'modified'
                    actions['IN_OPEN'] = 'read'
                    actions['IN_MOVE'] = 'modified'
                    actions['IN_CLOSE'] = 'read'

                    event['action'] = actions[change]
                    event['change_type'] = 'filesystem'
                    event['object_category'] = object_type
                    event['object_path'] = alert['path']
                    event['file_name'] = alert['name']
                    event['file_path'] = alert['tag']
                    event['pulsar_config'] = alert['pulsar_config']
                    if 'contents' in alert:
                        event['contents'] = alert['contents']

                    if alert['stats']:  # Gather more data if the change wasn't a delete
                        stats = alert['stats']
                        event['object_id'] = stats['inode']
                        event['file_acl'] = stats['mode']
                        event['file_create_time'] = stats['ctime']
                        event['file_modify_time'] = stats['mtime']
                        event['file_size'] = stats['size'] / 1024.0  # Convert bytes to kilobytes
                        event['user'] = stats['user']
                        event['group'] = stats['group']
                        if object_type == 'file':
                            chk = alert.get('checksum')
                            if chk:
                                event['file_hash'] = chk
                                event['file_hash_type'] = alert.get('checksum_type', 'unknown')

                else:  # Windows, win_pulsar
                    if alert.get('Accesses', None):
                        change = alert['Accesses']
                        if alert['Hash'] == 'Item is a directory':
                            object_type = 'directory'
                        else:
                            object_type = 'file'
                    else:
                        change = alert['Reason']
                        object_type = 'file'

                    actions = defaultdict(lambda: 'unknown')
                    actions['Delete'] = 'deleted'
                    actions['Read Control'] = 'read'
                    actions['Write DAC'] = 'acl_modified'
                    actions['Write Owner'] = 'modified'
                    actions['Synchronize'] = 'modified'
                    actions['Access Sys Sec'] = 'read'
                    actions['Read Data'] = 'read'
                    actions['Write Data'] = 'modified'
                    actions['Append Data'] = 'modified'
                    actions['Read EA'] = 'read'
                    actions['Write EA'] = 'modified'
                    actions['Execute/Traverse'] = 'read'
                    actions['Read Attributes'] = 'read'
                    actions['Write Attributes'] = 'acl_modified'
                    actions['Query Key Value'] = 'read'
                    actions['Set Key Value'] = 'modified'
                    actions['Create Sub Key'] = 'created'
                    actions['Enumerate Sub-Keys'] = 'read'
                    actions['Notify About Changes to Keys'] = 'read'
                    actions['Create Link'] = 'created'
                    actions['Print'] = 'read'
                    actions['Basic info change'] = 'modified'
                    actions['Compression change'] = 'modified'
                    actions['Data extend'] = 'modified'
                    actions['EA change'] = 'modified'
                    actions['File create'] = 'created'
                    actions['File delete'] = 'deleted'

                    if alert.get('Accesses', None):
                        event['action'] = actions[change]
                        event['change_type'] = 'filesystem'
                        event['object_category'] = object_type
                        event['object_path'] = alert['Object Name']
                        event['file_name'] = os.path.basename(alert['Object Name'])
                        event['file_path'] = os.path.dirname(alert['Object Name'])
                        event['pulsar_config'] = alert['pulsar_config']
                        # TODO: Should we be reporting 'EntryType' or 'TimeGenerated?
                        #   EntryType reports whether attempt to change was successful.
                    else:
                        for c in change:
                            if not event.get('action', None):
                                event['action'] = actions.get(c, c)
                            else:
                                event['action'] += ', ' + actions.get(c, c)
                        event['change_type'] = 'filesystem'
                        event['object_category'] = object_type
                        event['object_path'] = alert['Full path']
                        event['file_name'] = alert['File name']
                        event['file_path'] = alert['tag']
                        event['pulsar_config'] = alert.get('pulsar_config',
                                                           'trubblestack_pulsar_win_config.yaml')
                        event['TimeGenerated'] = alert['Time stamp']
                        chk = alert.get('checksum')
                        if chk:
                            event['file_hash'] = chk
                            event['file_hash_type'] = alert.get('checksum_type', 'unknown')

                event.update({'master': master})
                event.update({'minion_id': minion_id})
                event.update({'dest_host': fqdn})
                event.update({'dest_ip': fqdn_ip4})
                event.update({'dest_fqdn': local_fqdn})
                event.update({'system_uuid': __grains__.get('system_uuid')})

                event.update(cloud_details)

                for custom_field in custom_fields:
                    custom_field_name = 'custom_' + custom_field
                    custom_field_value = __salt__['config.get'](custom_field, '')
                    if isinstance(custom_field_value, (str, unicode)):
                        event.update({custom_field_name: custom_field_value})
                    elif isinstance(custom_field_value, list):
                        custom_field_value = ','.join(custom_field_value)
                        event.update({custom_field_name: custom_field_value})

                payload.update({'host': fqdn})
                payload.update({'index': opts['index']})
                payload.update({'sourcetype': opts['sourcetype']})

                # Remove any empty fields from the event payload
                remove_keys = [k for k in event if event[k] == ""]
                for k in remove_keys:
                    del event[k]

                payload.update({'event': event})

                # Potentially add metadata fields:
                fields = {}
                for item in index_extracted_fields:
                    if item in payload['event'] and not isinstance(payload['event'][item], (list, dict, tuple)):
                        fields[item] = str(payload['event'][item])

                if fields:
                    payload.update({'fields': fields})

                hec.batchEvent(payload)

            hec.flushBatch()
    except Exception:
        log.exception('Error ocurred in splunk_pulsar_return')
    return


def _dedupList(l):
    deduped = []
    for i, x in enumerate(l):
        if x not in l[i + 1:]:
            deduped.append(x)
    return deduped


def _get_options():
    if __salt__['grains.get']('trubblestack:returner:splunk'):
        splunk_opts = []
        returner_opts = __salt__['grains.get']('trubblestack:returner:splunk')
        if not isinstance(returner_opts, list):
            returner_opts = [returner_opts]
        for opt in returner_opts:
            processed = {}
            processed['token'] = opt.get('token')
            processed['indexer'] = opt.get('indexer')
            processed['port'] = str(opt.get('port', '8088'))
            processed['index'] = opt.get('index')
            processed['custom_fields'] = opt.get('custom_fields', [])
            processed['sourcetype'] = opt.get('sourcetype_pulsar', 'trubble_fim')
            processed['http_event_server_ssl'] = opt.get('hec_ssl', True)
            processed['proxy'] = opt.get('proxy', {})
            processed['timeout'] = opt.get('timeout', 9.05)
            processed['http_event_collector_ssl_verify'] = opt.get('http_event_collector_ssl_verify', True)
            if 'fallback_indexer' in opt and __grains__.get('ip_gw', None) is False:
                processed['indexer'] = opt['fallback_indexer']
            splunk_opts.append(processed)
        return splunk_opts
    elif __salt__['config.get']('trubblestack:returner:splunk'):
        splunk_opts = []
        returner_opts = __salt__['config.get']('trubblestack:returner:splunk')
        if not isinstance(returner_opts, list):
            returner_opts = [returner_opts]
        for opt in returner_opts:
            processed = {}
            processed['token'] = opt.get('token')
            processed['indexer'] = opt.get('indexer')
            processed['port'] = str(opt.get('port', '8088'))
            processed['index'] = opt.get('index')
            processed['custom_fields'] = opt.get('custom_fields', [])
            processed['sourcetype'] = opt.get('sourcetype_pulsar', 'trubble_fim')
            processed['http_event_server_ssl'] = opt.get('hec_ssl', True)
            processed['proxy'] = opt.get('proxy', {})
            processed['timeout'] = opt.get('timeout', 9.05)
            processed['http_event_collector_ssl_verify'] = opt.get('http_event_collector_ssl_verify', True)
            if 'fallback_indexer' in opt and __grains__.get('ip_gw', None) is False:
                processed['indexer'] = opt['fallback_indexer']
            splunk_opts.append(processed)
        return splunk_opts
    else:
        splunk_opts = {}
        splunk_opts['token'] = __salt__['config.get']('trubblestack:pulsar:returner:splunk:token').strip()
        splunk_opts['indexer'] = __salt__['config.get']('trubblestack:pulsar:returner:splunk:indexer')
        splunk_opts['port'] = __salt__['config.get']('trubblestack:pulsar:returner:splunk:port', '8088')
        splunk_opts['index'] = __salt__['config.get']('trubblestack:pulsar:returner:splunk:index')
        splunk_opts['custom_fields'] = __salt__['config.get']('trubblestack:pulsar:returner:splunk:custom_fields', [])
        splunk_opts['sourcetype'] = __salt__['config.get']('trubblestack:pulsar:returner:splunk:sourcetype')
        splunk_opts['http_event_server_ssl'] = __salt__['config.get']('trubblestack:pulsar:returner:splunk:hec_ssl', True)
        splunk_opts['proxy'] = __salt__['config.get']('trubblestack:pulsar:returner:splunk:proxy', {})
        splunk_opts['timeout'] = __salt__['config.get']('trubblestack:pulsar:returner:splunk:timeout', 9.05)
        splunk_opts['http_event_collector_ssl_verify'] = \
                       __salt__['config.get']('trubblestack:pulsar:returner:splunk:http_event_collector_ssl_verify', True)
        return [splunk_opts]


# Thanks to George Starcher for the http_event_collector class (https://github.com/georgestarcher/)
# Default batch max size to match splunk's default limits for max byte
# See http_input stanza in limits.conf; note in testing I had to limit to 100,000 to avoid http event collector breaking connection
# Auto flush will occur if next event payload will exceed limit

class http_event_collector:

    def __init__(self, token, http_event_server, host='', http_event_port='8088',
                 http_event_server_ssl=True, http_event_collector_ssl_verify=True,
                 max_bytes=_max_content_bytes, proxy=None, timeout=9.05):
        self.timeout = timeout
        self.token = token
        self.batchEvents = []
        self.maxByteLength = max_bytes
        self.currentByteLength = 0
        self.server_uri = []
        self.http_event_collector_ssl_verify = http_event_collector_ssl_verify
        if proxy and http_event_server_ssl:
            self.proxy = {'https': 'https://{0}'.format(proxy)}
        elif proxy:
            self.proxy = {'http': 'http://{0}'.format(proxy)}
        else:
            self.proxy = {}

        # Set host to specified value or default to localhostname if no value provided
        if host:
            self.host = host
        else:
            self.host = socket.gethostname()

        # Build and set server_uri for http event collector
        # Defaults to SSL if flag not passed
        # Defaults to port 8088 if port not passed

        servers = http_event_server
        if not isinstance(servers, list):
            servers = [servers]
        for server in servers:
            if http_event_server_ssl:
                self.server_uri.append(['https://%s:%s/services/collector/event' % (server, http_event_port), True])
            else:
                self.server_uri.append(['http://%s:%s/services/collector/event' % (server, http_event_port), True])

        if http_event_collector_debug:
            print self.token
            print self.server_uri

    def sendEvent(self, payload, eventtime=''):
        # Method to immediately send an event to the http event collector

        headers = {'Authorization': 'Splunk ' + self.token}

        # If eventtime in epoch not passed as optional argument use current system time in epoch
        if not eventtime:
            eventtime = str(int(time.time()))

        # Fill in local hostname if not manually populated
        if 'host' not in payload:
            payload.update({'host': self.host})

        # Update time value on payload if need to use system time
        data = {'time': eventtime}
        data.update(payload)

        # send event to http event collector
        r = requests.post(self.server_uri, data=json.dumps(data), headers=headers,
                          verify=self.http_event_collector_ssl_verify, proxies=self.proxy)

        # Print debug info if flag set
        if http_event_collector_debug:
            logger.debug(r.text)
            logger.debug(data)

    def batchEvent(self, payload, eventtime=''):
        # Method to store the event in a batch to flush later

        # Fill in local hostname if not manually populated
        if 'host' not in payload:
            payload.update({'host': self.host})

        # If eventtime in epoch not passed as optional argument and not in payload, use current system time in epoch
        if not eventtime and 'time' not in payload:
            eventtime = time.time()
            payload.update({'time': eventtime})

        payloadString = json.dumps(payload)
        payloadLength = len(payloadString)

        if (self.currentByteLength + payloadLength) > self.maxByteLength:
            self.flushBatch()
            # Print debug info if flag set
            if http_event_collector_debug:
                print 'auto flushing'
        else:
            self.currentByteLength = self.currentByteLength + payloadLength

        self.batchEvents.append(payloadString)

    def flushBatch(self):
        # Method to flush the batch list of events

        if len(self.batchEvents) > 0:
            headers = {'Authorization': 'Splunk ' + self.token}
            self.server_uri = [x for x in self.server_uri if x[1] is not False]
            success = False
            for server in self.server_uri:
                retries = -1
                max_retries = 0
                retry_sleep = 15
                if RETRY:
                    max_retries = __salt__['config.get']('returner_retry_max', 3)
                    retry_sleep = __salt__['config.get']('returner_retry_sleep', 15)
                while retries < max_retries:
                    retries += 1
                    if retries != 0:
                        log.info('RETRYING in {0} seconds'.format(retry_sleep))
                        time.sleep(retry_sleep)
                    try:
                        r = requests.post(server[0], data=' '.join(self.batchEvents), headers=headers,
                                          verify=self.http_event_collector_ssl_verify, proxies=self.proxy, timeout=self.timeout)
                        r.raise_for_status()
                        server[1] = True
                        success = True
                        break
                    except requests.exceptions.Timeout as timeout_err:
                        log.info('Connection timed out to splunk server {0}: {1}'.format(unicode(server[0]), unicode(timeout_err)))
                    except requests.exceptions.ConnectionError as connect_err:
                        log.info('Error establishing connection to splunk server {0}: {1}'.format(unicode(server[0]), unicode(connect_err)))
                    except requests.exceptions.HTTPError as http_err:
                        log.info('HTTP Error received while connecting to splunk server {0}: {1}'.format(unicode(server[0]), unicode(http_err)))
                    except requests.exceptions.RequestException as gen_err:
                        log.info('Request to splunk server {0} failed: {1}'.format(unicode(server[0]), unicode(gen_err)))
                        server[1] = False
                    except Exception as e:
                        log.error('Request to splunk threw an error: {0}'.format(e))
                if success:
                    break
            self.batchEvents = []
            self.currentByteLength = 0
