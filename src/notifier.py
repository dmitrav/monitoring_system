
import smtplib, time, traceback, base64, imaplib, json
import urllib.parse
import urllib.request
import requests
import lxml.html
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.constants import gmail_sender as SENDER
from src.constants import GOOGLE_CLIENT_ID, REFRESH_TOKEN_PATH, ACCESS_TOKEN_PATH, GOOGLE_CLIENT_SECRET, GOOGLE_ACCOUNTS_BASE_URL, REDIRECT_URI
from src.constants import error_recipients as ME
from src.constants import new_qcs_recipients as RECIPIENTS
from src import logger


def command_to_url(command):
    return '%s/%s' % (GOOGLE_ACCOUNTS_BASE_URL, command)


def url_escape(text):
    return urllib.parse.quote(text, safe='~-._')


def url_unescape(text):
    return urllib.parse.unquote(text)


def url_format_params(params):
    param_fragments = []
    for param in sorted(params.items(), key=lambda x: x[0]):
        param_fragments.append('%s=%s' % (param[0], url_escape(param[1])))
    return '&'.join(param_fragments)


def generate_permission_url(client_id, scope='https://mail.google.com/'):
    params = {}
    params['client_id'] = client_id
    params['redirect_uri'] = REDIRECT_URI
    params['scope'] = scope
    params['response_type'] = 'code'
    return '%s?%s' % (command_to_url('o/oauth2/auth'), url_format_params(params))


def call_authorize_tokens(client_id, client_secret, authorization_code):
    params = {}
    params['client_id'] = client_id
    params['client_secret'] = client_secret
    params['code'] = authorization_code
    params['redirect_uri'] = REDIRECT_URI
    params['grant_type'] = 'authorization_code'
    request_url = command_to_url('o/oauth2/token')
    response = urllib.request.urlopen(request_url, urllib.parse.urlencode(params).encode('UTF-8')).read().decode('UTF-8')
    return json.loads(response)


def call_refresh_token(client_id, client_secret, refresh_token):
    params = {}
    params['client_id'] = client_id
    params['client_secret'] = client_secret
    params['refresh_token'] = refresh_token
    params['grant_type'] = 'refresh_token'
    request_url = command_to_url('o/oauth2/token')
    response = urllib.request.urlopen(request_url, urllib.parse.urlencode(params).encode('UTF-8')).read().decode('UTF-8')
    return json.loads(response)


def generate_oauth2_string(username, access_token, as_base64=False):
    auth_string = 'user=%s\1auth=Bearer %s\1\1' % (username, access_token)
    if as_base64:
        auth_string = base64.b64encode(auth_string.encode('ascii')).decode('ascii')
    return auth_string


def test_imap(user, auth_string):
    imap_conn = imaplib.IMAP4_SSL('imap.gmail.com')
    imap_conn.debug = 4
    imap_conn.authenticate('XOAUTH2', lambda x: auth_string)
    imap_conn.select('INBOX')


def test_smpt(user, base64_auth_string):
    smtp_conn = smtplib.SMTP('smtp.gmail.com', 587)
    smtp_conn.set_debuglevel(True)
    smtp_conn.ehlo('test')
    smtp_conn.starttls()
    smtp_conn.docmd('AUTH', 'XOAUTH2 ' + base64_auth_string)


def get_authorization(google_client_id, google_client_secret):
    scope = "https://mail.google.com/"
    print('Navigate to the following URL to auth:', generate_permission_url(google_client_id, scope))
    authorization_code = input('Enter verification code: ')
    response = call_authorize_tokens(google_client_id, google_client_secret, authorization_code)
    return response['refresh_token'], response['access_token'], response['expires_in']


def refresh_authorization(google_client_id, google_client_secret):
    refresh_token = get_actual_token('refresh')
    response = call_refresh_token(google_client_id, google_client_secret, refresh_token)
    return response['access_token'], response['expires_in']


def get_actual_token(type):
    # read
    if type == 'access':
        with open(ACCESS_TOKEN_PATH, 'r') as f:
            creds = json.load(f)
        return creds['access_token']
    elif type == 'refresh':
        with open(REFRESH_TOKEN_PATH, 'r') as f:
            creds = json.load(f)
        return creds['refresh_token']


def send_mail(fromaddr, toaddr, subject, message):

    access_token, expires_in = refresh_authorization(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET)

    refresh_token()

    auth_string = generate_oauth2_string(fromaddr, access_token, as_base64=True)

    msg = MIMEMultipart('related')
    msg['Subject'] = subject
    msg['From'] = fromaddr
    msg['To'] = ','.join(toaddr)
    msg.preamble = 'This is a multi-part message in MIME format.'
    msg_alternative = MIMEMultipart('alternative')
    msg.attach(msg_alternative)
    part_text = MIMEText(lxml.html.fromstring(message).text_content().encode('utf-8'), 'plain', _charset='utf-8')
    part_html = MIMEText(message.encode('utf-8'), 'html', _charset='utf-8')
    msg_alternative.attach(part_text)
    msg_alternative.attach(part_html)

    server = smtplib.SMTP('smtp.gmail.com:587')
    server.ehlo(GOOGLE_CLIENT_ID)
    server.starttls()
    server.docmd('AUTH', 'XOAUTH2 ' + auth_string)
    server.sendmail(fromaddr, toaddr, msg.as_string())
    server.quit()


def send_new_qc_notification(qualities, info, in_debug_mode=False):
    """ This method sends a notification of a successful execution on a new QC file."""

    SUBJECT = 'New QC added'

    TEXT = 'Hi there,<br><br>' \
           'A new QC run with {} buffer has just been processed.<br>'.format(info['buffer']) + \
           '<b>Score:</b> ' + str(sum(qualities)) + '/' + str(len(qualities)) + '<br>' + \
           'Total: ' + str(info['total_qcs']) + \
           '<br>Details:<br>' \
           'http://imsb-nz-crazy/qc' \
           '<br><br>Cheers,<br>' \
           'Mass Spec Monitor'
    try:
        if in_debug_mode:
            send_mail(SENDER, ME, SUBJECT, TEXT)
        else:
            send_mail(SENDER, RECIPIENTS, SUBJECT, TEXT)
    except Exception:
        logger.print_qc_info("Notification failed!")
        logger.print_qc_info(traceback.format_exc())


def send_error_notification(filename, trace):
    """ This method sends a notification of an error caused by a new QC file."""

    SUBJECT = 'New QC crashed'

    TEXT = 'Hi there,<br><br>' \
           'The file ' + filename + ' caused an <b>unexpected error</b>:<br>' + trace + \
           '<br><br>Check out <i>qc_logs.txt</i> on the server.' \
           '<br><br>Cheers,<br>' \
           'Mass Spec Monitor'
    try:
        send_mail(SENDER, ME, SUBJECT, TEXT)
    except Exception:
        logger.print_qc_info("Notification failed!")
        logger.print_qc_info(traceback.format_exc())


def refresh_token():
    """ This method updates an access token. """

    with open(REFRESH_TOKEN_PATH, 'r') as f:
        creds = json.load(f)

    base64_encoded_clientid_clientsecret = base64.b64encode(str.encode(f'{GOOGLE_CLIENT_ID}:{GOOGLE_CLIENT_SECRET}'))  # concatenate with : and encode in base64
    base64_encoded_clientid_clientsecret = base64_encoded_clientid_clientsecret.decode('ascii')  # turn bytes object into ascii string

    url = f"{GOOGLE_ACCOUNTS_BASE_URL}/o/oauth2/token"
    headers = {'Content-Type': "application/x-www-form-urlencoded", 'Authorization': f'Basic {base64_encoded_clientid_clientsecret}'}
    data = {'grant_type': 'refresh_token', 'redirect_uri': REDIRECT_URI, 'refresh_token': creds['access_token']}

    r = requests.post(url, headers=headers, data=data)
    response = r.json()

    if response.get('access_token'):
        with open(REFRESH_TOKEN_PATH, 'w') as f:
            json.dump(response, f, indent=4)
    else:
        print('There was an error refreshing your access token.')
        print(r.text)


def update_token_manually():
    refresh_token, access_token, expires_in = get_authorization(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET)
    print('Set the following as your GOOGLE_REFRESH_TOKEN:', refresh_token)
    exit()


if __name__ == "__main__":

    start_time = time.time()
    fake_qualities = [1 for x in range(16)]
    # send_new_qc_notification(fake_qualities, {'buffer': 'IPA', 'total_qcs': 100})
    send_error_notification("new_file", "Value error")
    print("sending e-mail takes", time.time() - start_time, "s")