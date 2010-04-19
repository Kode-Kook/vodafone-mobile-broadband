# -*- coding: utf-8 -*-
# Copyright (C) 2006-2007  Vodafone Global
# Author:  Nicholas Herriot
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
# 51 Franklin Street, Fi1fth Floor, Boston, MA 02110-1301 USA.
"""
Controllers for Pay As You Talk
"""
import re
from datetime import datetime
from time import time

from wader.bcm.contrib.gtkmvc import Controller
from wader.bcm.dialogs import show_warning_dialog
from wader.bcm.logger import logger
from wader.bcm.network_codes import (get_payt_credit_check_info,
                                     get_payt_submit_voucher_info)
from wader.bcm.translate import _

from wader.common.oal import get_os_object


class PayAsYouTalkController(Controller):
    """Controller for the pay as you talk window"""

    def __init__(self, model):
        super(PayAsYouTalkController, self).__init__(model, spurious=True)

        self.tz = None
        try:
            self.tz = get_os_object().get_tzinfo()
        except:
            pass

    def register_view(self, view):
        """
        Fill the label fields of the pay as you talk dialog

        This will be called once the view is registered
        """
        super(PayAsYouTalkController, self).register_view(view)

        self.set_device_info()

    def set_device_info(self):
        self.get_cached_sim_credit()
        self.view.set_msisdn_value(self.model.msisdn)

        # Set initial button state
        if self.model.status in [_("Registered"), _("Roaming")]:
            self.view.enable_credit_button(True)
            self.view.enable_send_button(True)

    def _submit_voucher_by_ussd(self, ussd, voucher, cb):

        mccmnc, format, regex = ussd

        device = self.model.get_device()
        if not device:
            return

        # make sure we construct the string to enable PAYT Topup vouchers to be
        # used e.g. *#1345*<voucher number>#
        request = format % voucher

        def ussd_cb(response):
            match = re.search(regex, response)
            if match:
#                success = match.group('success')
                logger.info("PAYT SIM submit voucher via USSD success")
                cb(True)
            else:
                logger.info("PAYT SIM submit voucher didn't match USSD regex:"
                            " '%s'" % response)
                cb(None)

        def ussd_eb(error):
            logger.error("PAYT SIM error submitting voucher via USSD: %s"
                         % error)
            cb(None)

        device.Initiate(request,
                        reply_handler=ussd_cb,
                        error_handler=ussd_eb)

    def submit_voucher(self, _voucher):

        voucher = _voucher.strip()

        payt_available = self.model.get_sim_conf('payt_available', None)
        if payt_available == False: # Not a PAYT SIM
            show_warning_dialog(_("PAYT submit voucher"),
                                _("SIM is not on a PAYT plan"))
            return

        def submit_cb(success):
            if success:
                logger.info("PAYT SIM submit voucher success")
                # ok we established his voucher code is good, let's cause the
                # system to update the UI with his new credit. To do that we
                # need to fire off another request
                self.get_current_sim_credit()
            else:
                logger.error("PAYT SIM submit voucher success")
                show_warning_dialog(_("PAYT submit voucher"),
                                    _("PAYT submit voucher failed"))

            self.model.payt_submit_busy = False

        ussd = get_payt_submit_voucher_info(self.model.imsi)
        if ussd:
            self.model.payt_submit_busy = True
            self._submit_voucher_by_ussd(ussd, voucher, submit_cb)
        # elif have payt SMS submit voucher info:
        #    self._submit_voucher_by_sms()
        else:
            show_warning_dialog(_("PAYT submit voucher"),
                                _("No PAYT submit voucher method available"))

    def _get_current_sim_credit_by_ussd(self, ussd, cb):

        mccmnc, request, regex, format = ussd

        device = self.model.get_device()
        if not device:
            return

        def get_credit_cb(response):
            match = re.search(regex, response)
            if match:
                credit = format % match.group('value')
                cb(credit)
            else:
                logger.info("PAYT SIM credit '%s' didn't match USSD regex"
                            % response)
                cb(None)

        def get_credit_eb(error):
            logger.error("PAYT SIM error fetching via USSD: %s" % error)
            cb(None)

        device.Initiate(request,
                        reply_handler=get_credit_cb,
                        error_handler=get_credit_eb)

    def get_current_sim_credit(self):
        # my job is to obtain the current credit value. I take care of setting
        # both value and time as a credit amount is only valid at the time you
        # check. I store the values in Gconf and set a flag indicating whether
        # this SIM is prepay capable

        payt_available = self.model.get_sim_conf('payt_available', None)
        if payt_available == False: # Not a PAYT SIM
            show_warning_dialog(_("PAYT credit check"),
                                _("SIM is not on a PAYT plan"))
            return

        def credit_cb(credit):
            if credit:
                utc = time()
                now = datetime.fromtimestamp(utc, self.tz)
                logger.info("PAYT SIM credit: %s on %s" %
                                (credit, now.strftime("%c")))

                self.model.payt_credit_balance = credit
                self.model.set_sim_conf('payt_credit_balance', credit)

                self.model.payt_credit_date = now
                self.model.set_sim_conf('payt_credit_date', utc)
            else:
                self.model.payt_credit_balance = _("Not available")
                self.model.payt_credit_date = None

            # Record SIM as PAYT or not
            if not isinstance(payt_available, bool):
                self.model.payt_available = (credit is not None)
                self.model.set_sim_conf('payt_available',
                                        self.model.payt_available)

            self.model.payt_credit_busy = False

        ussd = get_payt_credit_check_info(self.model.imsi)
        if ussd:
            self.model.payt_credit_busy = True
            self._get_current_sim_credit_by_ussd(ussd, credit_cb)
        # elif have payt SMS credit check info:
        #    self._get_current_sim_credit_by_sms()
        else:
            show_warning_dialog(_("PAYT credit check"),
                                _("No PAYT credit check method available"))

    def get_cached_sim_credit(self):

        if self.model.get_sim_conf('payt_available'):
            credit = self.model.get_sim_conf('payt_credit_balance')
            utc = self.model.get_sim_conf('payt_credit_date')

            if credit and utc:
                now = datetime.fromtimestamp(utc, self.tz)
                logger.info("PAYT SIM credit from gconf: %s - %s" %
                                (credit, now.strftime("%c")))

                self.model.payt_credit_balance = credit
                self.model.payt_credit_date = now
                return

        self.model.payt_credit_balance = _("Not available")
        self.model.payt_credit_date = None

    # ------------------------------------------------------------ #
    #                       Properties Changed                     #
    # ------------------------------------------------------------ #

    def property_payt_credit_balance_value_change(self, model, old, new):
        self.view.set_credit_view(new)

    def property_payt_credit_date_value_change(self, model, old, new):
        self.view.set_credit_date(new)

    def property_payt_credit_busy_value_change(self, model, old, new):
        if new:
            # ok we need to tell the view to wipe current data and prepare for
            # the new! So let's remove our current credit and date first.
            self.view.set_waiting_credit_view()
        #    Could start a local throbber here
        #else:
        #    stop throbber image

        # disable buttons whilst busy
        self.view.enable_credit_button(not new)
        self.view.enable_send_button(not new)

    def property_payt_submit_busy_value_change(self, model, old, new):
        # disable buttons whilst busy
        self.view.enable_credit_button(not new)
        self.view.enable_send_button(not new)

    def property_msisdn_value_change(self, model, old, new):
        self.view.set_msisdn_value(new)

    def property_status_value_change(self, model, old, new):
        if new in [_("Registered"), _("Roaming")]:
            self.view.enable_credit_button(True)
            self.view.enable_send_button(True)

    # ------------------------------------------------------------ #
    #                       Signals Handling                       #
    # ------------------------------------------------------------ #

    def on_close_button_clicked(self, widget):
        self._hide_myself()

    def on_credit_button_clicked(self, widget):
        self.get_current_sim_credit()

    def on_send_voucher_button_clicked(self, widget):
        # ok when the send voucher button is clicked grab the value from the
        # view entry box and send to the network.
        voucher_code = self.view['voucher_code'].get_text().strip()
        self.submit_voucher(voucher_code)
        self.view.set_voucher_entry_view('')

    def _hide_myself(self):
        self.model.unregister_observer(self)
        self.view.hide()
