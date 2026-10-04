"""Presentation of recorded products; never identity, admission or learning.

Names are matched to normalized recipe source, not a client-chosen design id.
New installs freeze the display metadata; legacy receipts resolve on read.
"""
from copy import deepcopy
from functools import lru_cache
import json
from mcp import workshop, workshop_components


def named_sources():
    """Shared named variants used by Recipes and product presentation."""
    import starter_goals
    import goal_chains
    return [('Personal field pick',goal_chains.first_tool_recipe()),
            ('Camp stool',starter_goals.recipe()),('Work table',goal_chains.work_table_recipe()),
            ('Camp light',goal_chains.camp_light_recipe()),
            ('Camp solar panel',goal_chains.camp_solar_recipe()),
            ('Camp chair',goal_chains.exact_furniture_recipe('chair','starter-camp-chair')),
            ('Camp shelf',goal_chains.exact_furniture_recipe('shelf-unit','starter-camp-shelf'))]


# The starter variant a new player should make, keyed by the catalog design it
# stands in for. Recipes shows the catalog version beneath it, not beside it.
RECOMMENDED_OVER={'field-pick':'Personal field pick','stool':'Camp stool','table':'Work table',
                  'solar-array':'Camp solar panel','mine-lamp':'Camp light',
                  'chair':'Camp chair','shelf-unit':'Camp shelf'}


def source_key(recipe):
    design,overrides=workshop_components.design_from_spec(recipe)
    return json.dumps({'kind':design.kind,'parameters':dict(design.parameters),
                       'component_overrides':overrides},sort_keys=True,separators=(',',':'))


@lru_cache(maxsize=1)
def _named_keys():
    return {source_key(recipe):name for name,recipe in named_sources()}


def from_recipe(app,recipe):
    key=source_key(recipe)
    # A saved design's name is useful only for the version actually built.
    # Reusing a design id for a different source cannot borrow that name.
    ident=recipe.get('design_id')
    if ident:
        import workshop_store
        from workshop_api_core import _store
        try:
            record,design=workshop_store.load(_store(app),ident)
            saved={k:record.get(k,{}) for k in ('kind','parameters','component_overrides')}
            if source_key(saved)==key:
                return {'label':record['label'],'label_source':'saved-design'}
        except (OSError,ValueError,KeyError):pass
    label=_named_keys().get(key)
    if label:return {'label':label,'label_source':'named-recipe'}
    # A changed variant still has its assembly kind, without claiming it is
    # the original named recipe or that its declared purpose was validated.
    kind=str(recipe.get('kind') or 'built item')
    return {'label':kind.replace('-',' ').capitalize(),'label_source':'assembly-kind'}


def for_item(app,thing):
    names=set(thing.get('bodies',[]))
    receipt=next((r for r in reversed(getattr(app.room,'workshop_installs',[]) or [])
                  if r.get('status')=='installed' and names & (
                      set(r.get('root_bodies',[])) | set((r.get('component_to_body') or {}).values())
                      | {r.get('root_body')})),None)
    if receipt:
        presentation=deepcopy(receipt.get('presentation') or {})
        if not presentation:
            try:presentation=from_recipe(app,receipt['recipe'])
            except (KeyError,ValueError,TypeError):
                presentation={'label':'Built item','label_source':'legacy-receipt'}
        presentation.update(recipe=deepcopy(receipt.get('recipe')),design_id=receipt.get('design_id'))
    else:
        profile=next((p for p in app.room.spec.get('interactions',[]) if p.get('tool') in names),None)
        presentation={'label':(profile.get('object') if profile else None) or thing.get('name') or 'Item',
                      'label_source':'world-name'}
    if thing.get('separated_from'):
        components = [component for component, body in (receipt.get('component_to_body') or {}).items()
                      if body in names] if receipt else []
        part = ', '.join(components) or str(thing.get('name') or 'Part')
        label=presentation['label']
        presentation.update(label=label+' · '+part if label!=part else label,
                            separated=True, recipe=None, design_id=None)
    presentation['next_use']=['Hold / place in World','Open in Lab']
    if any(p.get('tool') in names and p.get('template')=='swing-and-lever'
           and set(p.get('parts') or [p.get('tool')]) <= names
           for p in app.room.spec.get('interactions',[])):
        presentation['next_use']=['Study / gather in World','Open in Lab']
    return presentation


def body_labels(app):
    """Small display index; body ids remain the keys used by all controls."""
    labels={}
    for receipt in getattr(app.room,'workshop_installs',[]) or []:
        if receipt.get('status')!='installed':continue
        presentation=receipt.get('presentation')
        if not presentation:
            try:presentation=from_recipe(app,receipt['recipe'])
            except (KeyError,ValueError,TypeError):presentation={'label':'Built item'}
        bodies=set(receipt.get('root_bodies',[])) | set((receipt.get('component_to_body') or {}).values())
        if receipt.get('root_body'):bodies.add(receipt['root_body'])
        labels.update({name:presentation['label'] for name in bodies})
    if getattr(app, 'live', None) and app.live.session is not None:
        import inventory_room
        for thing in inventory_room.items_of(app):
            if thing.get('separated_from'):
                label = for_item(app, thing)['label']
                labels.update({name:label for name in thing['bodies']})
    return labels
