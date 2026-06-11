import sys, json, time
sys.path.insert(0, 'sequences')
import provision_subdomain as ps

PRO = 're_iPPp8fht_BDGcHEtNrXGohe6QdMRL8GoX'
TOKEN = 'GhLG97qK5pSCjuXHBWZ7vWUGcgXvXZQm7sBUF56z4df6255b'
ROOT = 'mercuryscales.com'

# 10 new subdomains -> persona (matches the aureon/algoalpha 12-sub kit; outreach+team already exist)
NEW = [
    ('mail',     'leo',  'Leo Hartmann'),
    ('hi',       'ava',  'Ava Klein'),
    ('connect',  'noah', 'Noah Brandt'),
    ('partners', 'mia',  'Mia Vogel'),
    ('hello',    'finn', 'Finn Larsen'),
    ('reach',    'ella', 'Ella Novak'),
    ('news',     'jack', 'Jack Mercer'),
    ('send',     'nina', 'Nina Falk'),
    ('desk',     'sam',  'Sam Reuter'),
    ('hub',      'ruby', 'Ruby Aldridge'),
]

created = {}      # sub -> {id, records}
all_records = []  # flat list for one Hostinger push
for label, _, _ in NEW:
    sub = f'{label}.{ROOT}'
    c = ps.resend_create_domain(PRO, sub)
    created[label] = {'id': c.get('id'), 'records': c.get('records') or []}
    for rec in c.get('records') or []:
        all_records.append(ps._normalize(rec))
    all_records.append({'name': f'_dmarc.{label}', 'type': 'TXT',
                        'content': 'v=DMARC1; p=none; rua=mailto:dmarc@mercuryscales.com; '
                                   'ruf=mailto:dmarc@mercuryscales.com; pct=100; adkim=s; aspf=s'})
    print(f'created {sub} -> {c.get("id")} ({len(c.get("records") or [])} records)')

ok, msg = ps.hostinger_push_records(TOKEN, ROOT, all_records)
print('DNS push (', len(all_records), 'records):', ok, msg)

# verify all on PRO
ids = {f'{l}.{ROOT}': created[l]['id'] for l, _, _ in NEW}
for sub, rid in ids.items():
    try: ps.resend_verify_domain(PRO, rid)
    except Exception as e: print('verify trigger', sub, e)
deadline = time.time() + 60*14
pending = set(ids)
while pending and time.time() < deadline:
    for sub in list(pending):
        st = ps.resend_get_domain(PRO, ids[sub]).get('status')
        if st in ('verified', 'active'):
            pending.discard(sub); print('  verified', sub)
    if pending: time.sleep(20)
print('all verified:', not pending, '| still pending:', pending)

# update dorian.json: add 10 from_domains + 10 personas
cfg = json.load(open('profiles/dorian.json', encoding='utf-8'))
now = '2026-06-10T00:00:00Z'
for label, pslug, pname in NEW:
    sub = f'{label}.{ROOT}'
    cfg['relay']['from_domains'].append({
        'domain': sub, 'resend_domain_id': created[label]['id'],
        'verified_at': (now if sub not in pending else None),
        'warmup': {'enabled': True, 'current_day': 0, 'started_at': None,
                   'ramp_curve': 'snowball_v1', 'max_daily_sends': 50,
                   'reputation': {'bounce_rate_7d': 0.0, 'complaint_rate_7d': 0.0, 'delivered_7d': 0, 'last_check': None}}})
    cfg['personas'].append({
        'slug': pslug, 'from_name': pname, 'from_addr': f'{pslug}@{sub}',
        'reply_to': 'skiljodorian@gmail.com', 'title': 'Growth Partner, Mercury Scales',
        'voice': {'register': 'direct-peer',
                  'quirks': ['founder-to-founder, no agency-speak', 'one concrete question per email',
                             'references a real signal about their business'],
                  'avoid': ['hype', 'exclamation marks', 'guru language', 'fake scarcity']},
        'signature': f'{pname}\nGrowth Partner, Mercury Scales\nmercuryscales.com'})
cfg['rotation']['_comment'] = 'Capped per send_ramp; 12 subdomains x 12 personas (full kit), warmup-gated.'
json.dump(cfg, open('profiles/dorian.json', 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
print('dorian.json now has', len(cfg['relay']['from_domains']), 'domains and', len(cfg['personas']), 'personas')
