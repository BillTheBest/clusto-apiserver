#!/usr/bin/env python
#
# -*- mode:python; sh-basic-offset:4; indent-tabs-mode:nil; coding:utf-8 -*-
# vim:set tabstop=4 softtabstop=4 expandtab shiftwidth=4 fileencoding=utf-8:
#
# Copyright 2013, Jorge Gallegos <kad@blegh.net>

"""
The Clusto API Server will work as an alternative to the direct database
access traditional clusto commands and libraries use.

Sometimes your database has restricted access or you want to expose your clusto
information across facilities but don't want to risk opening up your database
port to the outside world or don't have the required know-how to do it in a
secure manner.

Exposing an HTTP(S) endpoint is a more common problem and as such there are
several well-understood solutions. Scalability and security are also points
you have to consider.

The Clusto API Server should thus have the following required features:

 *  Complete object manipulation: create, delete, insert, and remove objects,
    besides displaying them.
 *  Complete object attribute manipulation: add, delete, update, query, and
    displaying attributes
 *  Resource manipulation: allocate and deallocate objects from resources
 *  Querying

"""

import bottle
import clusto
from clusto import script_helper
import clustoapi
import functools
import inspect
import os
import string
import sys


DOC_SUBSTITUTIONS = {
    'get': "curl -X GET -G -s -w '\\nHTTP: %{http_code}\\nContent-type: %{content_type}'",
    'get_i': "curl -X GET -G -si",
    'post': "curl -X POST -s -w '\\nHTTP: %{http_code}\\nContent-type: %{content_type}'",
    'post_i': "curl -X POST -si",
    'put': "curl -X PUT -s -w '\\nHTTP: %{http_code}\\nContent-type: %{content_type}'",
    'put_i': "curl -X PUT -si",
    'delete': "curl -X DELETE -s -w '\\nHTTP: %{http_code}\\nContent-type: %{content_type}'",
    'delete_i': "curl -X DELETE -si",
    'head': "curl -s -I",
}

root_app = bottle.Bottle(autojson=False)


def _get_url(path=False):
    """
Returns the server's normalized URL
"""

    (scheme, netloc, qpath, qs, fragment) = bottle.request.urlparts
    if path:
        return u'%s://%s%s' % (scheme, netloc, qpath)
    else:
        return u'%s://%s' % (scheme, netloc)


@root_app.get('/favicon.ico')
def favicon():
    """
Send an HTTP code to clients so they stop asking for favicon. Example:

.. code:: bash

    $ ${get} -o /dev/null ${server_url}/favicon.ico
    HTTP: 410
    Content-type: text/html; charset=UTF-8

"""

    return bottle.HTTPResponse('', status=410)


@root_app.route('/', method='HEAD')
@root_app.get('/__version__')
def show_version():
    """
This shows the current version running, example

.. code:: bash

    $ ${get} ${server_url}/__version__
    "${server_version}"
    HTTP: 200
    Content-type: application/json

If you make a HEAD request to the / endpoint, the response is also the version
string, as that's less heavy to build than the regular / page:

.. code:: bash

    $ ${head} ${server_url}/
    HTTP/1.0 200 OK
    ...

    """

    return clustoapi.util.dumps(clustoapi.__version__)


def _get_mounts_and_modules():
    mods = {}
    for route in root_app.routes:
        mp = route.config.get('mountpoint')
        if mp:
            target = mp.get('target')
            if target and target.config.get('source_module'):
                mods[mp['prefix']] = target.config['source_module']
    return mods


@root_app.get('/__meta__')
def meta():
    """
This call just returns a mapping of all currently installed applications.

.. code:: bash

    $ ${get} ${server_url}/__meta__
    ...
    HTTP: 200
    Content-type: application/json

"""
    return clustoapi.util.dumps(_get_mounts_and_modules())


@root_app.get('/')
@root_app.get('/__doc__')
def build_docs(path='/', module=__name__):
    """
This will build documentation for the given module and all its methods.
If python-rest is available, it will attempt to parse it as a restructured
text document. You can get to the docs by going to the __doc__ endpoint on
each mounted application, the main __doc__ endpoint, or on the main endpoint:

.. code:: bash

    $ ${get} ${server_url}/__doc__
    <?xml version="1.0" encoding="utf-8" ?>
    ...
    HTTP: 200
    Content-type: text/html; charset=UTF-8

If you pass the ``Accept`` headers and specify ``text/plain``, you should get
the plain text version back

.. code:: bash

    $ ${get} -H 'Accept: text/plain' ${server_url}/__doc__
    ...
    HTTP: 200
    Content-type: text/plain

.. code:: bash

    $ diff -q <( curl -s -H 'Accept: text/plain' ${server_url}/__doc__ ) <( curl -s -H 'Accept: text/plain' ${server_url}/ ) && echo equal || echo diff
    equal

"""

#   Get the request path so we can look at the module index
    mod = sys.modules[module]
    docs = ['\n%s\n%s\n%s\n%s' % (
        '=' * len(mod.__name__),
        mod.__name__,
        '=' * len(mod.__name__),
        mod.__doc__)]

    if path == '/':
        mods = _get_mounts_and_modules()
        if mods:
            docs.append('\nMounted Applications\n%s\n' % ('-' * 20, ))
            for k, v in mods.items():
                docs.append(
                    '\n * `%s <${server_url}%s/__doc__>`_\n' % (v, k,)
                )

    docs.append('\nDocument strings for this module\n%s\n' % ('-' * 32,))
    toc = []
    methods = []
    for name in dir(mod):
        method = getattr(mod, name)
        if name != 'main' and not name.startswith('_') and inspect.isfunction(method):
            toc.append('\n * `%s()`_' % (name,))
            methods.append(
                '\n%s()\n%s\n%s' % (
                    name, '~' * (len(name) + 2), method.__doc__)
            )

    docs.extend(toc)
    docs.extend(methods)

    tpl = string.Template('\n'.join(docs))
    text = tpl.safe_substitute(
        server_url=_get_url(),
        server_version=clustoapi.__version__,
        **DOC_SUBSTITUTIONS
    )
    accept = bottle.request.headers.get('accept', 'text/plain')
    if accept != 'text/plain':
        try:
            from docutils import core
            return core.publish_string(source=text, writer_name='html')
        except ImportError:
            bottle.response.content_type = 'text/plain'
            return text
    else:
        bottle.response.content_type = 'text/plain'
        return text


def _configure(config={}, configfile=None):
    """
Configure the root app
"""

    if configfile:
        cfg = configfile
    else:
        cfg = os.environ.get(
            'CLUSTOCONFIG',
            '/etc/clusto/clusto.conf'
        )
    cfg = script_helper.load_config(cfg)
    clusto.connect(cfg)
#   This is an idempotent operation
    clusto.init_clusto()
    kwargs = {}
    kwargs['host'] = config.get(
        'host',
        script_helper.get_conf(
            cfg, 'apiserver.host', default='127.0.0.1'
        ),
    )
    kwargs['port'] = config.get(
        'port',
        script_helper.get_conf(
            cfg, 'apiserver.port', default=9664, datatype=int
        ),
    )
    kwargs['server'] = config.get(
        'server',
        script_helper.get_conf(
            cfg, 'apiserver.server', default='wsgiref'
        ),
    )
    kwargs['debug'] = config.get(
        'debug',
        script_helper.get_conf(
            cfg, 'apiserver.debug', default=False, datatype=bool
        )
    )
    kwargs['quiet'] = config.get(
        'quiet',
        script_helper.get_conf(
            cfg, 'apiserver.quiet', default=False, datatype=bool
        )
    )
    kwargs['reloader'] = config.get(
        'reloader',
        script_helper.get_conf(
            cfg, 'apiserver.reloader', default=False, datatype=bool
        )
    )
    mount_apps = config.get(
        'apps',
        script_helper.get_conf(
            cfg, 'apiserver.apps', default={}, datatype=dict
        )
    )

    root_app.route('/__doc__', 'GET', functools.partial(build_docs, '/', __name__))
    for mount_point, cls in mount_apps.items():
        module = __import__(cls, fromlist=[cls])
        root_app.mount(mount_point, module.bottle_app)
        path = '%s/__doc__' % (mount_point,)
        root_app.route(path, 'GET', functools.partial(build_docs, path, cls))

    return kwargs


def main():
    """
Main entry point for the clusto-apiserver console program
"""
    kwargs = _configure()
    root_app.run(**kwargs)


if __name__ == '__main__':
    sys.exit(main())
