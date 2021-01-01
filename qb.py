import requests
import json
import re
import time
import random
import math
import string
import sys
from datetime import date
from requests import RequestException
'''
conf = {
    'address':'127.0.0.1',
    'port':8081,
    'username':'admin',
    'password':'',
    'ipdat_path':'',
    'block':[], #like [{'str':'','type':''}]
    'refresh_day':'0'
}
'''

########## qbitorrent api ##########
class QbAPI:
    header_json = { 
        'Accept': 'application/json',
        'Accept-Encoding':'gzip, deflate, br'
    }
    def __init__(self, root_url, session):
        headers = {
            'Accept': 'text/javascript, text/html, application/xml, text/xml, */*',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'User-Agent': 'curl/7.72.0'
        }
        self.rid = self.newrid()
        self.root_url = root_url
        self.session = session
        #default header
        session.headers.update(headers)

    def newrid(self):
        return int(random.random()*1000)
    
    def getMaindata(self):
        url = self.root_url + '/api/v2/sync/maindata'
        content = {'rid': self.rid}
        rsp = self.session.get(url, params=content, headers=self.header_json)
        return json.loads(str(rsp.content, 'utf-8'))['torrents']
    
    #filter category sort reverse limit offset hashes
    #sort: size upspeed downspeed ratio
    def getTorrentList(self, tor_filter=None, sort=None, reverse=True, otherparams={}):
        url = self.root_url + '/api/v2/torrents/info'
        content = {'rid': self.rid}
        if tor_filter is not None:
            content['filter'] = tor_filter
        if sort is not None:
            content['sort'] = sort
        content['reverse'] = reverse
        for param in otherparams:
            content[param] = otherparams[param]
        rsp = self.session.get(url, params=content, headers=self.header_json)
        return json.loads(str(rsp.content, 'utf-8'))
    
    def getTorrentPeers(self, tro_hash):
        url = self.root_url + '/api/v2/sync/torrentPeers'
        content = {'hash':tro_hash, 'rid': self.rid}
        rsp = self.session.get(url, params=content, headers=self.header_json)
        return json.loads(str(rsp.content, 'utf-8'))
    
   
    def reloadIpFilter(self):
        url = self.root_url + '/api/v2/app/setPreferences'
        reload = {'ip_filter_enabled': False}
        content = {'json': json.dumps(reload, ensure_ascii=False)}
        session.post(url, content)
        time.sleep(2)
        reload = {'ip_filter_enabled': True}
        content = {'json': json.dumps(reload, ensure_ascii=False)}
        self.session.post(url, content)
    
   
    def login(self, username, password):
        url = self.root_url + '/api/v2/auth/login'
        response = self.session.post(url, {'username':username, 'password':password})
        return response.text

class Ipdat:
    # none for not found
    @staticmethod
    def matchBannedip(line):
        units = line.split(',') 
        if len(units) > 2 and units[2].strip() == 'banned':
            ip = units[0].split('-')
            if len(ip) > 0:
                return ip[0].strip()
        return None
    
    @staticmethod
    def loadIpdatFromFile(path, ipdat):
        #{ip}-{ip} , 127 , label
        if os.access(path, os.F_OK):
           with open(path, mode='r') as file_ips:
               for line in file_ips:
                   match = Ipdat.matchBannedip(line)
                   if match is not None:
                       ipdat.add(match)

    @staticmethod
    def writeIpdatToFile(path, ipdat, append=True):
        mode = 'a+' if append else 'w+'
        with open(path, mode=mode) as file_ips:
            new_ips = ''
            for ip in ipdat:
                new_ips = new_ips + ip + '-' + ip + ' , 127 , banned\n'
            file_ips.write(new_ips)



def isNeedBlockClient(self, peer):
    client = peer.get('client')
    if client is None:
        return False

    for deFilter in conf['block']:
        if int(deFilter['type']) == 1 and client.find(deFilter['str']) > -1:
            return True
        elif int(deFilter['type']) == 2 and client.startswith(deFilter['str']):
            return True

    return False
    

def blocking(conf):
    root_url = 'http://'+conf['address']+':'+conf['port']
    lasttime = date.today()
    session = requests.session()
    qb_api = QbAPI(root_url, session);

    #login
    if qb_api.login(conf['username'], conf['password']) != 'Ok.':
        exit(0)

    #set block ip

    blocked_ips = set()
    Ipdat.loadIpdatFromFile(conf['ipdat_path'], blocked_ips)
    print('There already have been '+str(len(blocked_ips))+' ips filtered')
    newblock_ips = set()
    print('The block clients are set to:' + str(conf['block']))
    #scaning
    print('begin scan torrents')
    while True:
        tor_list = qb_api.getTorrentList(tor_filter='active', sort='upspeed')

        for tor in tor_list:
            #the peersinfo is like { 'some':some, 'peers':{'ip:port':{'client':wanted,'upspeed':value}}}
            peersinfo = qb_api.getTorrentPeers(tor['hash'])
            if 'peers' not in peersinfo:
                continue
            for v in peersinfo['peers'].values():
                if v.get('ip') and (v['ip'] not in blocked_ips) and isNeedBlockClient(v):
                    print('find '+ v['client'] + ' at ' + v['ip'] + ', add to cache list')
                    newblock_ips.add(v['ip'])
            time.sleep(1)
        
        #refresh new block in file and apply
        if len(newblock_ips) > 0:
            blocked_ips.update(newblock_ips)
            Ipdat.writeIpdatToFile(conf['ipdat_path'], newblock_ips)
            print('apply and clean cache list')
            newblock_ips.clear()
        
        nowtime = date.today()
        re_internal = int(conf['refresh_day'])
        if re_internal > 0 and (nowtime - lasttime).days > re_internal:
            with open(conf['ipdat_path'],mode='w+') as file_ips:
                file_ips.write('')
            blocked_ips = newblock_ips = {}
            lasttime = nowtime
            print('blocked list cleaned')

        time.sleep(10)

def loadConfFromFile(conf_path):
    valid_key = {'address','port','username','password','ipdat_path','block','refresh_day'}
    conf = {'block':[]}
    with open(conf_path,mode='r') as conf_file:
        for line in conf_file:
            if line[0] == '#':
                continue
            match = re.match('([\w ]+?)=',line)
            if match is None:
                continue
            key = match.group(1).strip()
            if key not in valid_key:
                print('parser conf file error for: ', key, file=sys.stderr)
            value = re.search('=(\S+)',line)
            if value is not None:
                value = value.group(1).strip()
                if key == 'block':
                    value = re.match('(\S+?),(\S+)',value)
                    if value is not None:
                        conf[key].append({'str':value.group(1),'type':value.group(2)})
                else:
                    conf[key] = value
    return conf

    
def start(conf):
    while(True):
        try:
            blocking(conf)
        except requests.exceptions.RequestException as err:
            print ('OOps: Something Else',err)
        except requests.exceptions.HTTPError as errh:
            print ('Http Error:',errh)
        except requests.exceptions.ConnectionError as errc:
            print ('Error Connecting:',errc)
        except requests.exceptions.Timeout as errt:
            print ('Timeout Error:',errt)
        print('sleep 1 min')
        time.sleep(60)
     
if __name__ == '__main__':
    import argparse
    import os
    parser = argparse.ArgumentParser(description='ban specific clients for qbitorrent')
    parser.add_argument('-a','--address', default='localhost', help='qbitorrent-webui portal address')
    parser.add_argument('-p','--port', default='8080', help='qbitorrent-webui portal port')
    parser.add_argument('--username', default='admin', help='webui auth username')
    parser.add_argument('--password', help='webui auth passport')
    parser.add_argument('-c','--conf', default='bx.conf', help='conf file path')
    args = vars(parser.parse_args())
    conf = {}
    conf_path = args.pop('conf')
    if (conf_path is not None) and os.access(conf_path, os.F_OK):
        loadConfFromFile(conf_path)
    else:
        print('conf file not found', file=sys.stderr)
        exit(1)
    for arg in args:
        conf[arg] = args[arg]
    start(conf) 
