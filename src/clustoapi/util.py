#!/usr/bin/env python
#
# -*- mode:python; sh-basic-offset:4; indent-tabs-mode:nil; coding:utf-8 -*-
# vim:set tabstop=4 softtabstop=4 expandtab shiftwidth=4 fileencoding=utf-8:
#

import bottle
import clusto
import json


def get(name, driver=None):
    """
Tries to fetch a clusto object from a given name, optionally validating
the driver given. Returns:

 *  HTTP Error 404 if the object could not be found
 *  HTTP Error 409 if the object does not match the expected driver
 *  Clusto object otherwise
"""

    status = None
    obj = None
    msg = None
    try:
        if driver:
            obj = clusto.get_by_name(name, assert_driver=clusto.driverlist[driver])
        else:
            obj = clusto.get_by_name(name)

    except LookupError:
        status = 404
        msg = 'Object "%s" not found' % (name,)

    except TypeError:
        status = 409
        msg = 'The driver for object "%s" is not "%s"' % (name, driver,)

    return obj, status, msg


def dumps(obj, code=200, headers={}):
    """
"""
    return bottle.HTTPResponse(
        json.dumps(
            obj, indent=4, sort_keys=True,
            separators=(',', ': ')
        ),
        code,
        content_type='application/json',
        **headers
    )


def unclusto(obj):
    '''
    Convert an object to a representation that can be safely serialized into
    JSON.
    '''
    if type(obj) in (str, unicode, int) or obj is None:
        return obj
    if isinstance(obj, clusto.Attribute):
        return {
            'key': obj.key,
            'value': unclusto(obj.value),
            'subkey': obj.subkey,
            'number': obj.number,
            'datatype': obj.datatype
        }
    if issubclass(obj.__class__, clusto.Driver):
        return '/%s/%s' % (obj.driver, obj.name)
    return str(obj)


def show(obj):
    result = {}
    result['name'] = obj.name
    result['driver'] = obj.driver

    attrs = []
    for x in obj.attrs():
        attrs.append(unclusto(x))
    result['attrs'] = attrs
    result['contents'] = [unclusto(x) for x in obj.contents()]
    result['parents'] = [unclusto(x) for x in obj.parents()]

    return result
