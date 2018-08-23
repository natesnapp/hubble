'''
Trubblestack python log handler for splunk

Uses the same configuration as the rest of the splunk returners, returns to
the same destination but with an alternate sourcetype (``trubble_log`` by
default)

.. code-block:: yaml

    trubblestack:
      returner:
        splunk:
          - token: XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
            indexer: splunk-indexer.domain.tld
            index: trubble
            sourcetype_log: trubble_log

You can also add an `custom_fields` argument which is a list of keys to add to events
with using the results of config.get(<custom_field>). These new keys will be prefixed
with 'custom_' to prevent conflicts. The values of these keys should be
strings or lists (will be sent as CSV string), do not choose grains or pillar values with complex values or they will
be skipped:

.. code-block:: yaml

    trubblestack:
      returner:
        splunk:
          - token: XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
            indexer: splunk-indexer.domain.tld
            index: trubble
            sourcetype_log: trubble_log
            custom_fields:
              - site
              - product_group
'''
import socket

# Imports for http event forwarder
import requests
import json
import time
import copy
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import logging

_max_content_bytes = 100000
http_event_collector_debug = False

hec = None


class SplunkHandler(logging.Handler):
    '''
    Log handler for splunk
    '''
    def __init__(self):
        super(SplunkHandler, self).__init__()

        self.opts_list = _get_options()
        self.endpoint_list = []

        # Get cloud details
        cloud_details = __grains__.get('cloud_details', {})

        for opts in self.opts_list:
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

            minion_id = __grains__['id']
            master = __grains__['master']
            fqdn = __grains__['fqdn']
            # Sometimes fqdn is blank. If it is, replace it with minion_id
            fqdn = fqdn if fqdn else minion_id
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

            # Sometimes fqdn reports a value of localhost. If that happens, try another method.
            bad_fqdns = ['localhost', 'localhost.localdomain', 'localhost6.localdomain6']
            if fqdn in bad_fqdns:
                new_fqdn = socket.gethostname()
                if '.' not in new_fqdn or new_fqdn in bad_fqdns:
                    new_fqdn = fqdn_ip4
                fqdn = new_fqdn

            event = {}
            event.update({'master': master})
            event.update({'minion_id': minion_id})
            event.update({'dest_host': fqdn})
            event.update({'dest_ip': fqdn_ip4})
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

            payload = {}
            payload.update({'host': fqdn})
            payload.update({'index': opts['index']})
            payload.update({'sourcetype': opts['sourcetype']})

            # Potentially add metadata fields:
            fields = {}
            for item in index_extracted_fields:
                if item in event and not isinstance(event[item], (list, dict, tuple)):
                    fields[item] = str(event[item])
            if fields:
                payload.update({'fields': fields})

            self.endpoint_list.append((hec, event, payload))

    def emit(self, record):
        '''
        Emit a single record using the hec/event template/payload template
        generated in __init__()
        '''
        log_entry = self.format_record(record)
        for hec, event, payload in self.endpoint_list:
            event = copy.deepcopy(event)
            payload = copy.deepcopy(payload)
            event.update(log_entry)
            payload['event'] = event
            hec.batchEvent(payload, eventtime=time.time())
            hec.flushBatch()
        return True

    def emit_data(self, data):
        '''
        Add the given data (in dict format!) to the event template and emit as
        usual
        '''
        for hec, event, payload in self.endpoint_list:
            event = copy.deepcopy(event)
            payload = copy.deepcopy(payload)
            event.update(data)
            payload['event'] = event
            hec.batchEvent(payload, eventtime=time.time())
            hec.flushBatch()
        return True

    def format_record(self, record):
        '''
        Format the log record into a dictionary for easy insertion into a
        splunk event dictionary
        '''
        try:
            log_entry = {'message': record.message,
                         'level': record.levelname,
                         'timestamp': record.asctime,
                         'loggername': record.name,
                         }
        except:
            log_entry = {'message': record.msg,
                         'level': record.levelname,
                         'loggername': record.name,
                         }
        return log_entry


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
            processed['sourcetype'] = opt.get('sourcetype_log', 'trubble_log')
            processed['http_event_server_ssl'] = opt.get('hec_ssl', True)
            processed['proxy'] = opt.get('proxy', {})
            processed['timeout'] = opt.get('timeout', 9.05)
            processed['index_extracted_fields'] = opt.get('index_extracted_fields', [])
            processed['http_event_collector_ssl_verify'] = opt.get('http_event_collector_ssl_verify', True)
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
            processed['sourcetype'] = opt.get('sourcetype_log', 'trubble_log')
            processed['http_event_server_ssl'] = opt.get('hec_ssl', True)
            processed['proxy'] = opt.get('proxy', {})
            processed['timeout'] = opt.get('timeout', 9.05)
            processed['index_extracted_fields'] = opt.get('index_extracted_fields', [])
            processed['http_event_collector_ssl_verify'] = opt.get('http_event_collector_ssl_verify', True)
            splunk_opts.append(processed)
        return splunk_opts
    else:
        raise Exception('Cannot find splunk config at `trubblestack:returner:splunk`!')


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

        payloadLength = len(json.dumps(payload))

        if (self.currentByteLength + payloadLength) > self.maxByteLength:
            self.flushBatch()
            # Print debug info if flag set
            if http_event_collector_debug:
                print 'auto flushing'
        else:
            self.currentByteLength = self.currentByteLength + payloadLength

        # If eventtime in epoch not passed as optional argument use current system time in epoch
        if not eventtime:
            eventtime = str(int(time.time()))

        # Update time value on payload if need to use system time
        data = {'time': eventtime}
        data.update(payload)

        self.batchEvents.append(json.dumps(data))

    def flushBatch(self):
        # Method to flush the batch list of events

        if len(self.batchEvents) > 0:
            headers = {'Authorization': 'Splunk ' + self.token}
            self.server_uri = [x for x in self.server_uri if x[1] is not False]
            for server in self.server_uri:
                try:
                    r = requests.post(server[0], data=' '.join(self.batchEvents), headers=headers,
                                      verify=self.http_event_collector_ssl_verify,
                                      proxies=self.proxy, timeout=self.timeout)
                    r.raise_for_status()
                    server[1] = True
                    break
                except requests.exceptions.RequestException:
                    #log.info('Request to splunk server "%s" failed. Marking as bad.' % server[0])
                    server[1] = False
                except Exception as e:
                    #log.error('Request to splunk threw an error: {0}'.format(e))
                    pass
            self.batchEvents = []
            self.currentByteLength = 0
