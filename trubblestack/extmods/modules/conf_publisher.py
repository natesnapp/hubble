# -*- coding: utf-8 -*-
'''
Module to send config options to splunk
'''
import logging
import trubblestack.splunklogging
import copy
import time

log = logging.getLogger(__name__)


def publish(*args):

    '''
    Publishes config to splunk at an interval defined in schedule

    *args
       Tuple of opts to log (keys in __opts__). Only those key-value pairs would be published, keys for which are in *args
       If not passed, entire __opts__ (excluding password/token) would be published

    '''
    log.debug('Started publishing config to splunk')

    opts_to_log = {}
    if not args:
        opts_to_log = copy.deepcopy(__opts__)
    else:
        for arg in args:
            if arg in  __opts__:
                opts_to_log[arg] = __opts__[arg]

    trubblestack.splunklogging.__grains__ = __grains__
    trubblestack.splunklogging.__salt__ = __salt__
    trubblestack.splunklogging.__opts__ = __opts__

    filtered_conf = filter_config(opts_to_log)

    class MockRecord(object):
            def __init__(self, message, levelname, asctime, name):
                self.message = message
                self.levelname = levelname
                self.asctime = asctime
                self.name = name

    handler = trubblestack.splunklogging.SplunkHandler()
    handler.emit(MockRecord(filtered_conf, 'INFO', time.asctime(), 'trubblestack.trubble_config'))
    log.debug('Published config to splunk')


def filter_config(opts_to_log):
    '''
    Filters out keys containing certain patterns to avoid sensitive information being sent to splunk
    '''
    patterns_to_filter = ["password", "token"]
    filtered_conf = remove_sensitive_info(opts_to_log, patterns_to_filter)
    return filtered_conf


def remove_sensitive_info(obj, patterns_to_filter):
    '''
    Filter known sensitive info
    '''
    if isinstance(obj, dict):
         obj = {
             key: remove_sensitive_info(value, patterns_to_filter)
             for key, value in obj.iteritems()
             if not any(patt in key for patt in patterns_to_filter)}
    elif isinstance(obj, list):
         obj = [remove_sensitive_info(item, patterns_to_filter)
                    for item in obj]
    return obj
