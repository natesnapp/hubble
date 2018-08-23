# -*- coding: utf-8 -*-
'''
Attempt to load alternate splunk config from the trubble.d/ directory and store
in grains for use by the splunk returners. This way splunk config changes don't
require a trubble restart.
'''
import os
import yaml


def splunkconfig():
    '''
    Walk the trubble.d/ directory and read in any .conf files using YAML. If
    splunk config is found, place it in grains and return.
    '''
    configdir = os.path.join(os.path.dirname(__opts__['configfile']), 'trubble.d')
    ret = {}
    if not os.path.isdir(configdir):
        return ret
    try:
        for root, dirs, files in os.walk(configdir):
            for f in files:
                if f.endswith('.conf'):
                    fpath = os.path.join(root, f)
                    try:
                        with open(fpath, 'r') as fh:
                            config = yaml.safe_load(fh)
                        if config.get('trubblestack', {}).get('returner', {}).get('splunk'):
                            ret = {'trubblestack': config['trubblestack']}
                    except:
                        pass
    except:
        pass
    return ret
