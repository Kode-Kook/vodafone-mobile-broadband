# -*- coding: utf-8 -*-
# Copyright (C) 2006-2009  Vodafone España, S.A.
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
"""Controllers for the sms dialogs"""

from datetime import datetime
#from gtkmvc import Controller, Model
from wader.bcm.contrib.gtkmvc import Controller, Model

#import wader.common.exceptions as ex
from messaging import (PDU,
                       SEVENBIT_SIZE, UCS2_SIZE,
                       SEVENBIT_MP_SIZE, UCS2_MP_SIZE,
                       is_valid_gsm_text)

from wader.common.consts import SMS_INTFACE
from wader.common.oal import get_os_object
from wader.common.provider import NetworkProvider
from wader.common.sms import Message

from wader.bcm import dialogs
from wader.bcm.translate import _
from wader.bcm.logger import logger
from wader.bcm.messages import get_messages_obj
from wader.bcm.utils import get_error_msg
from wader.bcm.consts import APP_LONG_NAME

from wader.bcm.controllers.base import TV_DICT, TV_DICT_REV

from wader.bcm.views.contacts import ContactsListView
from wader.bcm.controllers.contacts import ContactsListController

from wader.bcm.contrib.ValidatedEntry import ValidatedEntry, v_phone


SMS_TOOLTIP = \
    _("You can send the SMS to several recipients separating them by commas")

IDLE, SENDING = range(2)


class NewSmsController(Controller):
    """Controller for the new sms dialog"""

    def __init__(self, model, parent_ctrl=None, contacts=None):
        super(NewSmsController, self).__init__(model)
        self.pdu = PDU()
        self.state = IDLE
        self.parent_ctrl = parent_ctrl
        self.max_length = SEVENBIT_SIZE
        self.numbers_entry = ValidatedEntry(v_phone)
        self.sms = None
        self.contacts = contacts

        try:
            self.numbers_entry.set_tooltip_text(SMS_TOOLTIP)
        except AttributeError:
            # This fails on Ubuntu Feisty, we can live without it
            pass

        self.tz = None
        try:
            self.tz = get_os_object().get_tzinfo()
        except:
            pass

    def register_view(self, view):
        super(NewSmsController, self).register_view(view)
        # set initial text
        msg = _('Text message: 0/%d chars') % self.max_length
        self.view.get_top_widget().set_title(msg)
        # signals stuff
        textbuffer = self.view['sms_edit_text_view'].get_buffer()
        textbuffer.connect('changed', self._textbuffer_changed)
        # show up
        self.numbers_entry.grab_focus()

    def close_controller(self):
        self.model.unregister_observer(self)
        self.view.get_top_widget().destroy()
        self.view = None
        self.model = None

    def on_delete_event_cb(self, *args):
        self.close_controller()

    def on_send_button_clicked(self, widget):
        # check that is a valid number
        if not self.numbers_entry.isvalid():
            self.numbers_entry.grab_focus()
            return

        # protect ourselves against multiple presses
        self.view.set_busy_view()

        text = self.get_message_text()
        if not text:
            resp = dialogs.show_warning_request_cancel_ok(
                    _("Send empty message"),
                    _("Are you sure you want to send an empty message?"))
            if not resp: # user said no
                self.view.set_idle_view()
                return

        def on_sms_sent_cb(msg):
            where = TV_DICT_REV['sent_treeview']
            self.save_messages_to_db([msg], where)

            # if original message is a draft, remove it
            if self.sms:
                self.delete_messages_from_db_and_tv([self.sms])
                self.sms = None

            # hide ourselves if we are not sending more SMS...
            if self.state == IDLE:
                if self.view:
                    self.view.set_idle_view()
                self.on_delete_event_cb(None)

        def on_sms_sent_eb(error):
            title = _('Error while sending SMS')
            dialogs.show_error_dialog(title, get_error_msg(error))

        self.state = SENDING

        def smsc_cb(smsc):
            logger.info("SMSC: %s" % smsc)

            numbers = self.get_numbers_list()
            for number in numbers:
                msg = Message(number, text, _datetime=datetime.now(self.tz))
                self.model.device.Send(dict(number=number, text=text,
                                            smsc=smsc),
                    dbus_interface=SMS_INTFACE,
                    reply_handler=lambda indexes: on_sms_sent_cb(msg),
                    error_handler=on_sms_sent_eb)

            self.state = IDLE

        def smsc_eb(*arg):
            title = _('No SMSC number')
            details = _("In order to send a SMS, %s needs to know the number "
                        "of your provider's SMSC. If you do not know the SMSC "
                        "number, contact your customer "
                        "service.") % APP_LONG_NAME
            dialogs.show_error_dialog(title, details)

            self.state = IDLE

        self.get_smsc(smsc_cb, smsc_eb)

    def get_smsc(self, cb, eb):
        """Get SMSC from preferences, networks DB or device, then callback"""

        # try to get from preferences
        if self.model.conf.get('preferences', 'use_alternate_smsc', False):
            alternate_smsc = self.model.conf.get('preferences',
                                                 'smsc_number', None)
        else:
            alternate_smsc = None

        # try to get from networks DB
        if self.model.imsi:
            provider = NetworkProvider()
            attrs = provider.get_network_by_id(self.model.imsi)
            if attrs:
                provider_smsc = attrs[0].smsc
            else:
                provider_smsc = None
            provider.close()
        else:
            provider_smsc = None

        # use the one from the best source
        if alternate_smsc is not None:
            logger.info("SMSC used from preferences")
            cb(alternate_smsc)
        elif provider_smsc is not None:
            logger.info("SMSC used from networks DB")
            cb(provider_smsc)
        else:
            logger.info("SMSC used from SIM")
            self.model.device.GetSmsc(dbus_interface=SMS_INTFACE,
                                      reply_handler=cb,
                                      error_handler=eb)

    def on_save_button_clicked(self, widget):
        """This will save the selected SMS to the drafts tv and the DB"""

        numl = self.get_numbers_list()
        nums = ','.join(numl) if numl else ''

        text = self.get_message_text()
        if text:
            msg = Message(nums, text, _datetime=datetime.now(self.tz))
            where = TV_DICT_REV['drafts_treeview']
            self.save_messages_to_db([msg], where)

        self.model.unregister_observer(self)
        self.view.hide()

    def on_cancel_button_clicked(self, widget):
        self.model.unregister_observer(self)
        self.view.hide()

    def on_contacts_button_clicked(self, widget):
        ctrl = ContactsListController(Model(), self, self.contacts)
        view = ContactsListView(ctrl)
        view.run()

    def _textbuffer_changed(self, textbuffer):
        """Handler for the textbuffer changed signal"""
        text = textbuffer.get_text(textbuffer.get_start_iter(),
                                   textbuffer.get_end_iter())
        if not len(text):
            msg = _('Text message: 0/%d chars') % SEVENBIT_SIZE
        else:
            # get the number of messages
            # we use a default number for encoding purposes
            num_sms = len(self.pdu.encode_pdu('+342453435', text))
            if num_sms == 1:
                max_length = SEVENBIT_SIZE if is_valid_gsm_text(text) else UCS2_SIZE
                args = dict(num=len(text), tot=max_length)
                msg = _('Text message: %(num)d/%(tot)d chars') % args
            else:
                max_length = SEVENBIT_MP_SIZE if is_valid_gsm_text(text) else UCS2_MP_SIZE
                used = len(text) - (max_length * (num_sms - 1))
                args = dict(num=used, tot=max_length, msgs=num_sms)
                msg = _('Text message: '
                        '%(num)d/%(tot)d chars (%(msgs)d SMS)') % args

        self.view.get_top_widget().set_title(msg)

    def get_message_text(self):
        """Returns the text written by the user in the textview"""
        textbuffer = self.view['sms_edit_text_view'].get_buffer()
        bounds = textbuffer.get_bounds()
        return textbuffer.get_text(bounds[0], bounds[1])

    def get_numbers_list(self):
        """Returns a list with all the numbers in the recipients_entry"""
        numbers_text = self.numbers_entry.get_text()
        numbers = numbers_text.split(',')
        if numbers[0] == '':
            return []
        return numbers

    def set_entry_text(self, text):
        self.numbers_entry.set_text(text)

    def save_messages_to_db(self, smslist, where):
        messages = get_messages_obj(self.parent_ctrl.model.get_device())
        smslistback = messages.add_messages(smslist, where)
        tv_name = TV_DICT[where]
        model = self.parent_ctrl.view[tv_name].get_model()
        model.add_messages(smslistback)

    def delete_messages_from_db_and_tv(self, smslist):
        messages = get_messages_obj(self.parent_ctrl.model.get_device())
        messages.delete_messages(smslist)
        model = self.parent_ctrl.view['drafts_treeview'].get_model()
        iter = model.get_iter_first()
        while iter:
            if model.get_value(iter, 4) in smslist:
                model.remove(iter)
            iter = model.iter_next(iter)


class ForwardSmsController(NewSmsController):
    """Controller for ForwardSms"""

    def __init__(self, model, parent_ctrl, contacts=None):
        super(ForwardSmsController, self).__init__(model, parent_ctrl, contacts)

    def set_recipient_numbers(self, text):
        self.numbers_entry.set_text(text)

    def set_textbuffer_text(self, text):
        textbuffer = self.view['sms_edit_text_view'].get_buffer()
        textbuffer.set_text(text)

    def set_textbuffer_focus(self):
        textwindow = self.view['sms_edit_text_view']
        textwindow.grab_focus()

    def set_processed_sms(self, sms):
        self.sms = sms
