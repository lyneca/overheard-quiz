import re
import requests
import string
import os

from pprint import pprint
from multiprocessing import Pool

import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from tqdm import tqdm

CHANNEL = os.environ['CHANNEL']

HEADERS = {
    'Content-Type': 'application/x-www-form-urlencoded'
}

ACCEPTED_OTHER_NAMES = [
    'student',
    'students',
    'bruce',
]

def get(url, **kwargs):
    kwargs.update({'token': os.environ['TOKEN']})
    resp = requests.get(url, headers=HEADERS, params=kwargs)
    if resp.ok:
        return resp.json()
    else:
        raise Exception(f'{resp.status_code} {resp.reason} {resp.content}')

def get_users():
    return get('https://slack.com/api/users.list')

def get_channel_history():
    return get('https://slack.com/api/channels.history', channel=CHANNEL, count=1000)
    #  return get('http://localhost:8765', channel=CHANNEL, count=1000)

print(":: extracting quotes")
print(" - downloading channel history...")
history = [x for x in get_channel_history()['messages']
           if x['type'] == 'message'
          and 'subtype' not in x
          and 'thread_ts' not in x]

def extract_components(msg):
    match = re.match(r'^["“”](.+)["“”]\s*[~—-]*\s*(?:<@(.+?)>(.+)?|(.+))', msg['text'].strip())
    if not match:
        return None
    groups = match.groups()
    if groups[1]:
        return {
            'quote': groups[0],
            'quoter_user': msg['user'],
            'quoted_user': groups[1],
            'is_id': True,
            'extra': groups[2],
        }
    elif groups[3].lower() in ACCEPTED_OTHER_NAMES:
        return {
            'quote': groups[0],
            'quoter_user': msg['user'],
            'quoted_user': groups[3].capitalize(),
            'is_id': False,
            'extra': '',
        }
    return None

def process_name(user):
    parts = user.split()
    print(user, '=>', ' '.join(
        [parts[0].capitalize()] + [x[0].upper() + '.' for x in parts[1:] if x[0] in string.ascii_letters]
    ))
    return ' '.join(
        [parts[0].capitalize()] + [x[0].upper() + '.' for x in parts[1:] if x[0] in string.ascii_letters]
    )

print(" - parsing quotes...")
quotes = [extract_components(x) for x in history]
quotes = list(filter(lambda x: x, quotes))

print(" - downloading users...")
users = {
    user['id']: (process_name(user['real_name']), user['profile']['image_512'], user['name'])
    for user in get_users()['members']
    if not user['is_bot']
}

#  for quote in quotes:
    #  quoter = quote['quoter_user']
    #  quoted = quote['quoted_user']
    #  if quote['is_id']:
        #  print(f"{users[quoter][0]} quoted {users[quoted][0]} saying \"{quote['quote']}\"")
    #  else:
        #  print(f"{users[quoter][0]} quoted {quoted} saying \"{quote['quote']}\"")

print(':: uploading quotes')
print(' - initialising firebase')
cred = credentials.Certificate('service-account.json')
firebase_admin.initialize_app(cred, {
  'projectId': os.environ['APP'],
})

db = firestore.client()

def format_quote(quote):
    def repl(match):
        return '@' + users[match.group(1)][0]
    return re.sub(r'<@(U\w+)>', repl, quote)

def upload(quote):
    ref = db.collection('quotes').document()
    ref.set({
        'quote': format_quote(quote['quote']),
        'quotedName': users[quote['quoted_user']][0] if quote['is_id'] else quote['quoted_user'],
        'quotedPhotoUrl': users[quote['quoted_user']][1] if quote['is_id'] else '',
        'quoterName': users[quote['quoter_user']][0],
        'quoterPhotoUrl': users[quote['quoter_user']][1],
        'is_id': quote['is_id'],
    })

print(' - uploading quotes')
print()
with Pool() as pool:
    list(tqdm(pool.imap(upload, quotes), total=len(quotes)))

print()
print(':: done.')
