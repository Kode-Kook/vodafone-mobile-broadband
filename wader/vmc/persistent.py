# -*- coding: utf-8 -*-
# Copyright (C) 2006-2007  Vodafone España, S.A.
# Author:  Pablo Martí
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
"""
Data persistance for VMC
"""

import datetime

from zope.interface import implements

from vmc.common.encoding import to_u
import vmc.common.consts as consts

from vmc.contrib.epsilon.extime import Time
from vmc.contrib.axiom import item, attributes, store
from vmc.contrib.axiom.attributes import AND


class AxiomDBManager(object):
    """
    Base class for all the database managers
    """
    def __init__(self, path):
        super(AxiomDBManager, self).__init__()
        self.store = store.Store(path)

    def close(self):
        self.store.close()
        self.store = None


class DBNetworkOperator(item.Item):
    netid = attributes.textlist(allowNone=False)
    name = attributes.text(allowNone=False)
    country = attributes.text(allowNone=False)
    type = attributes.text(allowNone=False)
    smsc = attributes.text(allowNone=False)
    apn = attributes.text(allowNone=False)
    username = attributes.text(allowNone=False)
    password = attributes.text(allowNone=False)
    dns1 = attributes.text(allowNone=True)
    dns2 = attributes.text(allowNone=True)

    def __repr__(self):
        return '<%s netid=%s>' % (self.__class__.__name__, self.netid)

    def get_name(self):
        return self.name

    def get_full_name(self):
        return self.name + ' ' + self.country


class NetworkOperatorManager(AxiomDBManager):
    def __init__(self, path=None):
        super(NetworkOperatorManager, self).__init__(path)

    def populate_networks(self, network_list):
        for net in network_list:
            dns1 = net.dns1 and to_u(net.dns1) or None
            dns2 = net.dns2 and to_u(net.dns2) or None
            DBNetworkOperator(store=self.store,
                              netid=net.netid,
                              name=to_u(net.name),
                              country=to_u(net.country),
                              type=to_u(net.type),
                              smsc=to_u(net.smsc),
                              apn=to_u(net.apn),
                              username=to_u(net.username),
                              password=to_u(net.password),
                              dns1=dns1,
                              dns2=dns2)

    def get_network_by_id(self, netid):
        # XXX: O(N) here!
        for network in self.store.query(DBNetworkOperator):
            for n in network.netid:
                if str(netid).startswith(n):
                    return network
        return None

    def get_all_networks_by_id(self, netid):
        # XXX: O(N) here!
        list=[]
        for network in self.store.query(DBNetworkOperator):
            for n in network.netid:
                if str(netid).startswith(n):
                    list.append(network)
                    break
        if len(list) > 0:
            return list
        else:
            return None

# net_manager singleton
net_manager = NetworkOperatorManager()


class UsageItem(item.Item):
    umts = attributes.boolean(allowNone=False)
    start_time = attributes.timestamp(allowNone=False)
    end_time = attributes.timestamp(allowNone=False)
    bits_recv = attributes.integer(allowNone=False)
    bits_sent = attributes.integer(allowNone=False)

    def __repr__(self):
        _type = (self.umts == True) and 'UMTS' or 'GPRS'
        args = (_type, self.end_time - self.start_time,
                self.bits_recv + self.bits_sent)

        return "<%s UsageItem time: %s total bits: %d>" % args

    def __eq__(self, other):
        if not isinstance(other, UsageItem):
            raise ValueError("Cannot reliably compare myself with %s" % other)

        return self.storeID == other.storeID

    def __ne__(self, other):
        return not self.__eq__(other)


class UsageManager(AxiomDBManager):
    def __init__(self, path=consts.USAGE_DB):
        super(UsageManager, self).__init__(path)

    def add_usage_item(self, umts, start, end, bits_recv, bits_sent):
        return UsageItem(store=self.store,
                         umts=umts,
                         start_time=start,
                         end_time=end,
                         bits_recv=bits_recv,
                         bits_sent=bits_sent)

    def get_usage_for_day(self, dateobj):
        """
        Returns all C{UsageItem} for day C{dateobj}
        """
        if not isinstance(dateobj, datetime.date):
            raise ValueError("Don't know what to do with %s" % dateobj)

        today = dateobj.timetuple()
        tomorrow = (dateobj + datetime.timedelta(hours=24)).timetuple()

        return list(self.store.query(UsageItem,
                    AND(UsageItem.start_time >= Time.fromStructTime(today),
                        UsageItem.end_time < Time.fromStructTime(tomorrow)))
                )

    def get_usage_for_month(self, dateobj):
        """
        Returns all C{UsageItem} for month C{dateobj}
        """
        if not isinstance(dateobj, datetime.date):
            raise ValueError("Don't know what to do with %s" % dateobj)

        first_current_month_day = dateobj.replace(day=1).timetuple()
        if dateobj.month < 12:
            nextmonth = dateobj.month + 1
            nextyear = dateobj.year
        else:
            nextmonth = 1
            nextyear = dateobj.year + 1

        first_next_month_day = dateobj.replace(day=1, month=nextmonth,
                                                year=nextyear).timetuple()

        return list(self.store.query(UsageItem,
                AND(UsageItem.start_time >= Time.fromStructTime(
                                            first_current_month_day),
                    UsageItem.start_time < Time.fromStructTime(
                                            first_next_month_day)))
                )

# singleton
usage_manager = UsageManager()

