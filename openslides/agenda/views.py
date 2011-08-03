#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
    openslides.agenda.views
    ~~~~~~~~~~~~~~~~~~~~~~~

    Views for the agenda app.

    :copyright: 2011 by the OpenSlides team, see AUTHORS.
    :license: GNU GPL, see LICENSE for more details.
"""
try:
    import json
except ImportError:
    import simplejson as json

from datetime import datetime

from django.http import HttpResponse
from django.shortcuts import render_to_response, redirect
from django.template import RequestContext
from django.core.urlresolvers import reverse
from django.contrib import messages
from django.utils.translation import ugettext as _

from openslides.agenda.models import Item
from openslides.agenda.api import get_active_item, is_summary, children_list

from openslides.agenda.forms import ElementOrderForm, MODELFORM
from openslides.application.models import Application
from openslides.assignment.models import Assignment
from openslides.poll.models import Poll
from openslides.system.api import config_set, config_get
from openslides.utils.template import render_block_to_string
from openslides.utils.utils import template, permission_required, \
                                   del_confirm_form
from openslides.utils.pdf import print_agenda
from poll.models import Poll, Option

def view(request, item_id):
    """
    Shows the Slide.
    """
    item = Item.objects.get(id=item_id)
    votes = assignment_votes(item)
    
    return render_to_response('beamer/%s.html' % item.type,
                             {
                                 'item': item.cast(),
                                 'ajax': 'off',
                                 'votes': votes,
                             },
                             context_instance=RequestContext(request))


@permission_required('agenda.can_see_beamer')
def beamer(request):
    """
    Shows a active Slide.
    """
    data = {'ajax': 'on'}
    template = ''
    try:
        item = get_active_item()
        votes = assignment_votes(item)
        if is_summary():
            items = item.children.filter(hidden=False)
            data['items'] = items
            data['title'] = item.title
            template = 'beamer/overview.html'
        else:
            data['item'] = item.cast()
            data['title'] = item.title
            data['votes'] = votes
            template = 'beamer/%s.html' % (item.type)
    except Item.DoesNotExist:
        items = Item.objects.filter(parent=None).filter(hidden=False) \
                            .order_by('weight')
        data['items'] = items
        data['title'] = _("Agenda")
        template = 'beamer/overview.html'

    if request.is_ajax():
        content = render_block_to_string(template, 'content', data)
        jsondata = {'content': content,
                    'title': data['title'],
                    'time': datetime.now().strftime('%H:%M')}
        return HttpResponse(json.dumps(jsondata))
    else:
        return render_to_response(template,
                                  data,
                                  context_instance=RequestContext(request))


def assignment_votes(item):
    votes = []
    if item.type == "ItemAssignment":
      assignment = item.cast().assignment
      # list of candidates
      candidates = set()
      for option in Option.objects.filter(poll__assignment=assignment):
          candidates.add(option.value)
      # list of votes
      votes = []
      for candidate in candidates:
          tmplist = []
          tmplist.append(candidate)
          for poll in assignment.poll_set.all():
              if candidate in poll.options_values:
                  option = Option.objects.filter(poll=poll).filter(user=candidate)[0]
                  if poll.optiondecision:
                      tmplist.append([option.yes, option.no, option.undesided])
                  else:
                      tmplist.append(option.yes)
              else:
                  tmplist.append("-")
          votes.append(tmplist)

    return votes


@permission_required('agenda.can_view_agenda')
@template('agenda/overview.html')
def overview(request):
    """
    Shows an overview of all items.
    """
    if request.method == 'POST':
        for item in Item.objects.all():
            form = ElementOrderForm(request.POST, prefix="i%d" % item.id)
            if form.is_valid():
                try:
                    item.parent = Item.objects.get( \
                                       id=form.cleaned_data['parent'])
                except Item.DoesNotExist:
                    item.parent = None
                item.weight = form.cleaned_data['weight']
                item.save()

    items = children_list(Item.objects.filter(parent=None).order_by('weight'))
    try:
        overview = is_summary() and not get_active_item()
    except Item.DoesNotExist:
        overview = True
    return {
        'items': items,
        'overview': overview,
        'summary': is_summary()
        }


@permission_required('agenda.can_manage_agenda')
def set_active(request, item_id, summary=False):
    """
    Set an Item as the active one.
    """
    if item_id == "0":
        config_set("presentation", "0")
    else:
        try:
            item = Item.objects.get(id=item_id)
            item.set_active(summary)
        except Item.DoesNotExist:
            messages.error(request, _('Item ID %d does not exist.') % int(item_id))
    return redirect(reverse('item_overview'))


@permission_required('agenda.can_manage_agenda')
def set_closed(request, item_id, closed=True):
    """
    Close or open an Item.
    """
    try:
        item = Item.objects.get(id=item_id)
        item.set_closed(closed)
    except Item.DoesNotExist:
        messages.error(request, _('Item ID %d does not exist.') % int(item_id))
    return redirect(reverse('item_overview'))


@permission_required('agenda.can_manage_agenda')
@template('agenda/edit.html')
def edit(request, item_id=None, form='ItemText', default=None):
    """
    Show a form to edit an existing Item, or create a new one.
    """
    if item_id is not None:
        try:
            item = Item.objects.get(id=item_id).cast()
        except Item.DoesNotExist:
            messages.error(request, _('Item ID %d does not exist.') % int(item_id))
            return redirect(reverse('item_overview'))
    else:
        item = None

    if request.method == 'POST':
        if item_id is None:
            form = MODELFORM[form](request.POST)
        else:
            form = item.edit_form(request.POST)

        if form.is_valid():
            item = form.save()
            if item_id is None:
                messages.success(request, _('New item was successfully created.'))
                if "application" in request.POST:
                    item.application.writelog(_('Agenda item created'), request.user)
            else:
                messages.success(request, _('Item was successfully modified.'))
                if "application" in request.POST:
                    item.application.writelog(_('Agenda item modified'), request.user)
            return redirect(reverse('item_overview'))
        messages.error(request, _('Please check the form for errors.'))
    else:
        initial = {}
        if default:
            if form == "ItemAssignment":
                assignment = Assignment.objects.get(pk=default)
                initial = {
                    'assignment': assignment,
                    'title': assignment.name,
                }
            elif form == "ItemApplication":
                application = Application.objects.get(pk=default)
                initial = {
                    'application': application,
                    'title': application.title,
                }
            elif form == "ItemPoll":
                poll = Poll.objects.get(pk=default)
                initial = {
                    'poll': poll,
                    'title': poll.title,
                }

        if item_id is None:
            form = MODELFORM[form](initial=initial)
        else:
            form = item.edit_form()
    return { 'form': form,
             'item': item }


@permission_required('agenda.can_manage_agenda')
def delete(request, item_id):
    """
    Delete an Item.
    """
    item = Item.objects.get(id=item_id).cast()
    if request.method == 'POST':
        item.delete()
        messages.success(request, _("Item <b>%s</b> was successfully deleted.") % item)
    else:
        del_confirm_form(request, item)
    return redirect(reverse('item_overview'))