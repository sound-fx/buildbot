# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members


import weakref

import mock

from twisted.internet import defer
from twisted.internet import reactor

from buildbot import config
from buildbot.data.graphql import GraphQLConnector
from buildbot.test import fakedb
from buildbot.test.fake import bworkermanager
from buildbot.test.fake import endpoint
from buildbot.test.fake import fakedata
from buildbot.test.fake import fakemq
from buildbot.test.fake import pbmanager
from buildbot.test.fake.botmaster import FakeBotMaster
from buildbot.test.fake.machine import FakeMachineManager
from buildbot.util import service


class FakeCache:

    """Emulate an L{AsyncLRUCache}, but without any real caching.  This
    I{does} do the weakref part, to catch un-weakref-able objects."""

    def __init__(self, name, miss_fn):
        self.name = name
        self.miss_fn = miss_fn

    def get(self, key, **kwargs):
        d = self.miss_fn(key, **kwargs)

        @d.addCallback
        def mkref(x):
            if x is not None:
                weakref.ref(x)
            return x
        return d

    def put(self, key, val):
        pass


class FakeCaches:

    def get_cache(self, name, miss_fn):
        return FakeCache(name, miss_fn)


class FakeBuilder:

    def __init__(self, master=None, buildername="Builder"):
        if master:
            self.master = master
            self.botmaster = master.botmaster
        self.name = buildername


class FakeLogRotation:
    rotateLength = 42
    maxRotatedFiles = 42


class FakeMaster(service.MasterService):

    """
    Create a fake Master instance: a Mock with some convenience
    implementations:

    - Non-caching implementation for C{self.caches}
    """

    def __init__(self, reactor,
                 master_id=fakedb.FakeBuildRequestsComponent.MASTER_ID):
        super().__init__()
        self._master_id = master_id
        self.reactor = reactor
        self.objectids = {}
        self.config = config.MasterConfig()
        self.caches = FakeCaches()
        self.pbmanager = pbmanager.FakePBManager()
        self.initLock = defer.DeferredLock()
        self.basedir = 'basedir'
        self.botmaster = FakeBotMaster()
        self.botmaster.setServiceParent(self)
        self.name = 'fake:/master'
        self.masterid = master_id
        self.workers = bworkermanager.FakeWorkerManager()
        self.workers.setServiceParent(self)
        self.machine_manager = FakeMachineManager()
        self.machine_manager.setServiceParent(self)
        self.log_rotation = FakeLogRotation()
        self.db = mock.Mock()
        self.next_objectid = 0
        self.config_version = 0

        def getObjectId(sched_name, class_name):
            k = (sched_name, class_name)
            try:
                rv = self.objectids[k]
            except KeyError:
                rv = self.objectids[k] = self.next_objectid
                self.next_objectid += 1
            return defer.succeed(rv)
        self.db.state.getObjectId = getObjectId

    def getObjectId(self):
        return defer.succeed(self._master_id)

    def subscribeToBuildRequests(self, callback):
        pass

# Leave this alias, in case we want to add more behavior later


def make_master(testcase, wantMq=False, wantDb=False, wantData=False,
                wantRealReactor=False, wantGraphql=False, url=None, **kwargs):
    if wantRealReactor:
        _reactor = reactor
    else:
        assert testcase is not None, "need testcase for fake reactor"
        # The test case must inherit from TestReactorMixin and setup it.
        _reactor = testcase.reactor

    master = FakeMaster(_reactor, **kwargs)
    if url:
        master.buildbotURL = url
    if wantData:
        wantMq = wantDb = True
    if wantMq:
        assert testcase is not None, "need testcase for wantMq"
        master.mq = fakemq.FakeMQConnector(testcase)
        master.mq.setServiceParent(master)
    if wantDb:
        assert testcase is not None, "need testcase for wantDb"
        master.db = fakedb.FakeDBConnector(testcase)
        master.db.setServiceParent(master)
    if wantData:
        master.data = fakedata.FakeDataConnector(master, testcase)
    if wantGraphql:
        master.graphql = GraphQLConnector()
        master.graphql.setServiceParent(master)
        master.graphql.data = master.data.realConnector
        master.data._scanModule(endpoint)
        master.config.www = {'graphql': {"debug": True}}
        try:
            master.graphql.reconfigServiceWithBuildbotConfig(master.config)
        except ImportError:
            pass
    return master
