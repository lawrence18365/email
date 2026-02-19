import requests, os
from dotenv import load_dotenv
load_dotenv()
url = os.getenv('TURSO_DATABASE_URL').replace('libsql://', 'https://') + '/v2/pipeline'
token = os.getenv('TURSO_AUTH_TOKEN')
h = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

def q(sql):
    r = requests.post(url, headers=h, json={'requests': [{'type':'execute','stmt':{'sql':sql}},{'type':'close'}]}, timeout=15)
    res = r.json()['results'][0]['response']['result']
    return [[c['value'] if c['type'] != 'null' else None for c in row] for row in res['rows']]

print('=== LEAD STATUS BREAKDOWN ===')
for r in q('SELECT status, COUNT(*) FROM leads GROUP BY status ORDER BY COUNT(*) DESC'):
    print(f'  {r[0]}: {r[1]}')

total = q('SELECT COUNT(*) FROM leads')[0][0]
sent = q('SELECT COUNT(*) FROM sent_emails')[0][0]
unique_emailed = q('SELECT COUNT(DISTINCT lead_id) FROM sent_emails')[0][0]
responses = q('SELECT COUNT(*) FROM responses')[0][0]
unique_responded = q('SELECT COUNT(DISTINCT lead_id) FROM responses')[0][0]

print(f'\nTotal leads: {total}')
print(f'Total emails sent: {sent}')
print(f'Unique leads emailed: {unique_emailed}')
print(f'Total responses: {responses}')
print(f'Unique leads who responded: {unique_responded}')
print(f'Response rate: {int(unique_responded)/max(int(unique_emailed),1)*100:.1f}%')

print('\n=== RESPONDED LEADS ===')
for r in q('SELECT l.id, l.first_name, l.last_name, l.status, l.email FROM leads l INNER JOIN (SELECT DISTINCT lead_id FROM responses) resp ON l.id = resp.lead_id ORDER BY l.id'):
    print(f'  #{r[0]} {r[1]} {r[2]} | {r[3]} | {r[4]}')

print('\n=== BOUNCED / COMPLAINED ===')
for r in q("SELECT id, first_name, last_name, status, email FROM leads WHERE status IN ('bounced','complained') ORDER BY id"):
    print(f'  #{r[0]} {r[1]} {r[2]} | {r[3]} | {r[4]}')
bounced = q("SELECT COUNT(*) FROM leads WHERE status = 'bounced'")[0][0]
print(f'  Total bounced: {bounced}')
