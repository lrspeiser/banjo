"""Setup editing of declared Sandbox apparatus; never live body teleporting.

Kits and connected hinge/slide assemblies move together. Loose bodies remain
individual. Attached sources and connection points follow their owning body;
removal prunes dependent declarations and is checked before it is committed.
"""
import copy
import math
import machine_world as mw


def objects(base):
    compiled = mw.compile_spec(base)
    groups = {('kit:' + k['name']): {'name': k['name'], 'parts': []}
              for k in base.get('kits', [])}
    for p in compiled['parts']:
        key = 'kit:' + p['kit'] if p.get('kit') else 'part:' + p['name']
        groups.setdefault(key, {'name': p['name'], 'parts': []})['parts'].append(p['name'])
    # A pin/slide/weld needs its supporting bodies in the same edit. Springs,
    # ropes and drums connect independently placeable apparatus instead.
    for j in compiled['joints']:
        if j['kind'] not in ('hinge', 'slide', 'weld', 'fix'): continue
        owners = [k for k, g in groups.items() if j.get('a') in g['parts'] or j.get('b') in g['parts']]
        if len(owners) > 1:
            first = owners[0]
            for other in owners[1:]:
                groups[first]['parts'] += groups.pop(other)['parts']
    positions = {p['name']: p['at_m'] for p in compiled['parts']}
    return [dict(id=key, name=g['name'], parts=g['parts'], at_m=positions[g['parts'][0]])
            for key, g in groups.items() if g['parts']]


def references(value, names):
    if isinstance(value, str): return value in names or value.split(':')[0] in names
    if isinstance(value, list): return any(references(v, names) for v in value)
    if isinstance(value, dict): return any(references(v, names) for k, v in value.items()
                                          if k not in ('name', 'title', 'shows', 'law', 'maturity'))
    return False


def edit(base, object_id, delta=None, remove=False):
    original = copy.deepcopy(base)
    rows = objects(original)
    selected = next((r for r in rows if r['id'] == object_id), None)
    if not selected: raise ValueError('That Sandbox object is no longer in the design.')
    names = set(selected['parts'])
    compiled = mw.compile_spec(original)
    kit_names = {p['kit'] for p in compiled['parts'] if p['name'] in names and p.get('kit')}
    if remove:
        original['parts'] = [p for p in original.get('parts', []) if p['name'] not in names]
        original['kits'] = [k for k in original.get('kits', []) if k['name'] not in kit_names]
        names |= kit_names
        for j in compiled['joints']:
            if references(j, names): names.add(j['name'])
        # Names of removed joints/devices/batteries propagate to consumers.
        sections = [original] + [original[k] for k in ('electrical', 'light', 'thermo')
                                 if isinstance(original.get(k), dict)]
        changed = True
        while changed:
            changed = False
            for section in sections:
                for key, values in list(section.items()):
                    if key == 'parts' or not isinstance(values, list): continue
                    kept = []
                    for row in values:
                        if (isinstance(row, dict) or key=='mirrors' and isinstance(row,str)) and references(row, names):
                            if isinstance(row,dict) and row.get('name'):
                                names.add(row['name'])
                                if key == 'kits':
                                    names.update(p['name'] for p in compiled['parts'] if p.get('kit') == row['name'])
                                    names.update(j['name'] for j in compiled['joints'] if references(j, names))
                            changed = True
                        else: kept.append(row)
                    section[key] = kept
        original.setdefault('electrical', {})['wires'] = [w for w in original.get('electrical', {}).get('wires', [])
                                                          if not references(w, names)]
    else:
        if not mw._is_vec3(delta) or any(not math.isfinite(v) or abs(v) > 20 for v in delta):
            raise ValueError('Move the object by finite metres within the workbench.')
        for k in original.get('kits', []):
            if k['name'] in kit_names:
                k['translated_m'] = [round(a+b, 6) for a, b in zip(k.get('translated_m', [0, 0, 0]), delta)]
        mw.shift_rows(delta, [p for p in original.get('parts', []) if p['name'] in names])
        for j in original.get('joints', []):
            a, b = j.get('a') in names, j.get('b') in names
            if a and b: mw.shift_rows(delta, [j])
            elif j.get('drum') in kit_names or j.get('drum') in names:
                j['centre_m'] = [a+b for a, b in zip(j['centre_m'], delta)]
            if j.get('load') in names and 'load_point_m' in j:
                j['load_point_m'] = [a+b for a, b in zip(j['load_point_m'], delta)]
            if j['kind'] == 'pulley':
                for endpoint, point in (('a', 'over_a_m'), ('b', 'over_b_m')):
                    if j.get(endpoint) in names and point in j:
                        j[point] = [a+b for a, b in zip(j[point], delta)]
        for section in [original] + [original[k] for k in ('electrical', 'light', 'thermo') if isinstance(original.get(k), dict)]:
            for key, values in section.items():
                if key in ('parts', 'kits', 'joints') or not isinstance(values, list): continue
                for row in values:
                    if not isinstance(row, dict) or not references(row, names): continue
                    mw.shift_rows(delta, [row])
                    if isinstance(row.get('terminals'), dict):
                        row['terminals'] = {key: [a+b for a, b in zip(at, delta)] for key, at in row['terminals'].items()}
                    if isinstance(row.get('handle'), dict): mw.shift_rows(delta, [row['handle']])
    # Refuse unsupported dependencies atomically rather than leave a broken save.
    result = mw.compile_spec(original)
    return original, selected, result


def ghost(base, object_id, delta, snapping=False, snap_hold=None, nearby=False):
    import machine_alignment
    next_base, selected, compiled = edit(base, object_id, delta)
    initial = {p['name']:p for p in mw.compile_spec(base)['parts']}
    selected_names=set(selected['parts']);problems=[]
    suggestion=None
    # A prepared loose sphere gets the same local lane seating as a tray
    # marble. Translating a whole multi-body assembly is never auto-snapped.
    selected_parts=[p for p in compiled['parts'] if p['name'] in selected_names]
    if nearby and len(selected_parts)==1 and selected_parts[0]['shape']=='sphere' and not selected_parts[0]['fixed']:
        ball=selected_parts[0]
        p=dict(diameter_m=ball['size_m'][0],placement='at height')
        choices=machine_alignment.seat_candidates(p,ball,compiled)
        eligible=[q for q in choices if q['distance'] <= (machine_alignment.RELEASE_M
            if snap_hold==q['to']+'|'+q['port'] else machine_alignment.CAPTURE_M)]
        if eligible:
            candidate=min(eligible,key=lambda q:q['distance'])
            change=[candidate['at'][i]-ball['at_m'][i] for i in range(3)]
            shifted=[delta[i]+change[i] for i in range(3)]
            # Reuse the ordinary overlap/ground checks at the proposed pose.
            fitted=ghost(base,object_id,shifted) if math.hypot(*change)>.006 else None
            if not fitted or fitted['fits']:
                moved=math.hypot(*change)>.006
                if snapping or not moved:
                    suggestion=dict(candidate,knobs=dict(x_m=candidate['at'][0],z_m=candidate['at'][2],height_m=shifted[1]),moved=moved,nearby=True)
    def depth(a,b):
        return max(mw.overlap_depth(sa,sb) for sa in mw.solids_of(a) for sb in mw.solids_of(b))
    for a in compiled['parts']:
        if a['name'] not in selected_names:continue
        for b in compiled['parts']:
            if b['name'] in selected_names:continue
            current=depth(a,b)
            # Preserve an authored bolted overlap; moving farther into an
            # unrelated body is refused rather than creating penetration.
            allowed=max(.001,depth(initial[a['name']],initial[b['name']]))
            if current>allowed+1e-6:problems.append(f'{a["name"]} goes {current*1000:.0f} mm into {b["name"]}; move it')
    return dict(base=next_base, parts=[p for p in compiled['parts'] if p['name'] in selected['parts']],
                fits=not problems, problems=problems, cost=0, sun=[], selected=selected,airflows=compiled.get('airflows',[]),
                alignment=machine_alignment.guide(compiled, selected_names),**({'snap':suggestion} if suggestion else {}))
