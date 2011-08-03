#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
    openslides.assignment.views
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Views for the assignment app.

    :copyright: 2011 by the OpenSlides team, see AUTHORS.
    :license: GNU GPL, see LICENSE for more details.
"""

from django.shortcuts import redirect
from django.core.urlresolvers import reverse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils.translation import ugettext as _

from poll.models import Poll, Option
from poll.forms import OptionResultForm, PollInvalidForm
from assignment.models import Assignment
from assignment.forms import AssigmentForm, AssigmentRunForm
from utils.utils import template, permission_required, gen_confirm_form, del_confirm_form
from utils.pdf import print_assignment_poll
from participant.models import Profile


@permission_required('assignment.can_view_assignment')
@template('assignment/overview.html')
def get_overview(request):
    query = Assignment.objects
    if 'status' in request.GET and '---' not in request.GET['status']:
        query = query.filter(status__iexact=request.GET['status'])
    try:
        sort = request.GET['sort']
        if sort in ['name','status']:
            query = query.order_by(sort)
    except KeyError:
        pass
    if 'reverse' in request.GET:
        query = query.reverse()

    assignments = query.all()
    return {
        'assignments': assignments,
    }


@permission_required('assignment.can_view_assignment')
@template('assignment/view.html')
def view(request, assignment_id=None):
    form = None
    assignment = Assignment.objects.get(pk=assignment_id)
    if request.method == 'POST':
        if request.user.has_perm('assignment.can_nominate_other'):
            form = AssigmentRunForm(request.POST)
            if form.is_valid():
                user = form.cleaned_data['candidate']
                try:
                    assignment.run(user)
                    messages.success(request, _("Candidate <b>%s</b> was nominated successfully.") % (user))
                except NameError, e:
                    messages.error(request, e)
    else:
        if request.user.has_perm('assignment.can_nominate_other'):
            form = AssigmentRunForm()

    # list of candidates
    candidates = set()
    for option in Option.objects.filter(poll__assignment=assignment):
        candidates.add(option.value)

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

    return {'assignment': assignment,
            'form': form,
            'votes': votes}


@permission_required('assignment.can_manage_assignment')
@template('assignment/edit.html')
def edit(request, assignment_id=None):
    """
    View zum editieren und neuanlegen von Wahlen
    """
    if assignment_id is not None:
        assignment = Assignment.objects.get(id=assignment_id)
    else:
        assignment = None

    if request.method == 'POST':
        form = AssigmentForm(request.POST, instance=assignment)
        if form.is_valid():
            form.save()
            if assignment_id is None:
                messages.success(request, _('New election was successfully created.'))
            else:
                messages.success(request, _('Election was successfully modified.'))
            return redirect(reverse("assignment_overview"))
    else:
        form = AssigmentForm(instance=assignment)
    return {
        'form': form,
        'assignment': assignment,
    }


@permission_required('assignment.can_manage_assignment')
def delete(request, assignment_id):
    assignment = Assignment.objects.get(pk=assignment_id)
    if request.method == 'POST':
        assignment.delete()
        messages.success(request, _('Election <b>%s</b> was successfully deleted.') % assignment)
    else:
        del_confirm_form(request, assignment)
    return redirect(reverse('assignment_overview'))


@permission_required('assignment.can_manage_assignment')
@template('assignment/view.html')
def set_status(request, assignment_id=None, status=None):
    try:
        if status is not None:
            assignment = Assignment.objects.get(pk=assignment_id)
            assignment.set_status(status)
            messages.success(request, _('Election status was set to: <b>%s</b>.') % assignment.get_status_display())
    except Assignment.DoesNotExist:
        pass
    return redirect(reverse('assignment_view', args=[assignment_id]))


@permission_required('assignment.can_nominate_self')
def run(request, assignment_id):
    assignment = Assignment.objects.get(pk=assignment_id)
    try:
        assignment.run(request.user.profile)
        messages.success(request, _('You have set your candidature successfully.') )
    except NameError, e:
        messages.error(request, e)
    except Profile.DoesNotExist:
        messages.error(request,
                       _("You can't candidate. Your user account is only for administration."))
    return redirect(reverse('assignment_view', args=assignment_id))


@login_required
def delrun(request, assignment_id):
    assignment = Assignment.objects.get(pk=assignment_id)
    assignment.delrun(request.user.profile)
    messages.success(request, _("You have withdrawn your candidature successfully.") )
    return redirect(reverse('assignment_view', args=assignment_id))


@permission_required('assignment.can_manage_assignment')
def delother(request, assignment_id, profile_id):
    assignment = Assignment.objects.get(pk=assignment_id)
    profile = Profile.objects.get(pk=profile_id)

    if request.method == 'POST':
        assignment.delrun(profile)
        messages.success(request, _("Candidate <b>%s</b> was withdrawn successfully.") % (profile))
    else:
        gen_confirm_form(request,
                       _("Do you really want to withdraw <b>%s</b> from the election?") \
                        % profile, reverse('assignment_delother', args=[assignment_id, profile_id]))
    return redirect(reverse('assignment_view', args=assignment_id))


@permission_required('assignment.can_manage_assignment')
def gen_poll(request, assignment_id, ballotnumber):
    try:
        poll = Assignment.objects.get(pk=assignment_id).gen_poll()
        messages.success(request, _("New ballot was successfully created.") )
    except Assignment.DoesNotExist:
        pass
    return redirect(reverse('assignment_poll_view', args=[poll.id, ballotnumber]))


@permission_required('assignment.can_view_assignment')
@template('assignment/poll_view.html')
def poll_view(request, poll_id, ballotnumber=1):
    poll = Poll.objects.get(pk=poll_id)
    options = poll.options.order_by('user__user__first_name')
    assignment = poll.assignment
    if request.user.has_perm('assignment.can_manage_assignment'):
        if request.method == 'POST':
            form = PollInvalidForm(request.POST, prefix="poll")
            if form.is_valid():
                poll.voteinvalid = form.cleaned_data['invalid'] or 0
                poll.save()

            success = 0
            for option in options:
                option.form = OptionResultForm(request.POST, prefix="o%d" % option.id)
                if option.form.is_valid():
                    option.voteyes = option.form.cleaned_data['yes']
                    option.voteno = option.form.cleaned_data['no'] or 0
                    option.voteundesided = option.form.cleaned_data['undesided'] or 0
                    option.save()
                    success = success + 1
            if success == options.count():
                messages.success(request, _("Votes are successfully saved.") )
        else:
            form = PollInvalidForm(initial={'invalid': poll.voteinvalid}, prefix="poll")
            for option in options:
                option.form = OptionResultForm(initial={
                    'yes': option.voteyes,
                    'no': option.voteno,
                    'undesided': option.voteundesided,
                }, prefix="o%d" % option.id)
    return {
        'poll': poll,
        'form': form,
        'options': options,
        'ballotnumber': ballotnumber,
    }


@permission_required('assignment.can_manage_assignment')
def delete_poll(request, poll_id):
    poll = Poll.objects.get(pk=poll_id)
    assignment = poll.assignment
    ballot = assignment.poll_set.filter(id__lte=poll_id).count()
    if request.method == 'POST':
        poll.delete()
        messages.success(request, _('The %s. ballot was successfully deleted.') % ballot)
    else:
        del_confirm_form(request, poll, name=_("the %s. ballot") % ballot)
    return redirect(reverse('assignment_view', args=[assignment.id]))