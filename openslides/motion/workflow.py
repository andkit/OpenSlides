from django.conf import settings
from django.core import exceptions
from django.utils.importlib import import_module

from openslides.config.models import config
ugettext = lambda s: s

_workflow = None

class State(object):
    def __init__(self, id, name, next_states=[], poll=False, support=False):
        self.id = id
        self.name = name
        self.next_states = next_states
        self.poll = poll
        self.support = support

    def __unicode__(self):
        return self.name


def motion_workflow_choices():
    for workflow in settings.MOTION_WORKFLOW:
        yield workflow[0], workflow[1]


def get_state(state='default'):
    global _workflow
    if _workflow is not None:
        return _workflow[state]
    _workflow = {}
    for workflow in settings.MOTION_WORKFLOW:
        if workflow[0] == config['motion_workflow']:
            try:
                wf_module, wf_default_state_name = workflow[2].rsplit('.', 1)
            except ValueError:
                raise exceptions.ImproperlyConfigured(
                    '%s isn\'t a workflow module' % workflow[2])
            try:
                mod = import_module(wf_module)
            except ImportError as e:
                raise exceptions.ImproperlyConfigured(
                    'Error importing workflow %s: "%s"' % (wf_module, e))
            try:
                default_state = getattr(mod, wf_default_state_name)
            except AttributeError:
                raise exceptions.ImproperlyConfigured(
                    'Workflow module "%s" does not define a "%s" State'
                    % (wf_module, wf_default_state_name))
            _workflow['default'] = default_state
            break
    else:
        raise ImproperlyConfigured('Unknown workflow %s' % conf['motion_workflow'])

    populate_workflow(default_state, _workflow)
    return get_state(state)

def populate_workflow(state, workflow):
    workflow[state.id] = state
    for s in state.next_states:
        if s.id not in workflow:
            populate_workflow(s, workflow)


default_workflow = State('pub', ugettext('Published'), support=True, next_states=[
    State('per', ugettext('Permitted'), poll=True, next_states=[
        State('acc', ugettext('Accepted')),
        State('rej', ugettext('Rejected')),
        State('wit', ugettext('Withdrawed')),
        State('adj', ugettext('Adjourned')),
        State('noc', ugettext('Not Concerned')),
        State('com', ugettext('Commited a bill')),
        State('rev', ugettext('Needs Review'))]),
    State('nop', ugettext('Rejected (not authorized)'))])
