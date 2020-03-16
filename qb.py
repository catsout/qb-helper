import requests
import json
import re
import time
import random
import math
import string

from requests import RequestException

headers = {
    'Accept': 'text/javascript, text/html, application/xml, text/xml, */*',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/78.0.3904.70 Safari/537.36 '
}

conf = {
    "ip":"127.0.0.1",
    "port":8081,
    "username":"admin",
    "password":"",
    "ipdat_path":"",
    "block":[] #like [{"str":"","type":""}]
}


def newrid():
    return int(random.random()*1000)

def getMaindata(root_url, session, rid):
    url = root_url + '/api/v2/sync/maindata'
    content = {'rid': rid}
    headers_tmp = headers.copy()
    headers_tmp['Accept'] = 'application/json'
    headers_tmp['Accept-Encoding'] = 'gzip, deflate, br'
    rsp = session.get(url, params=content, headers=headers_tmp)
    return json.loads(str(rsp.content, 'utf-8'))['torrents']

#filter category sort reverse limit offset hashes
#sort: size upspeed downspeed ratio
def getTorrentList(root_url, session, rid, tor_filter=None, sort=None, reverse=True, otherparams={}):
    url = root_url + '/api/v2/torrents/info'
    headers_tmp = headers.copy()
    headers_tmp['Accept'] = 'application/json'
    headers_tmp['Accept-Encoding'] = 'gzip, deflate, br'
    content = {'rid': rid}
    if tor_filter is not None:
        content["filter"] = tor_filter
    if tor_filter is not None:
        content["sort"] = sort
        content["reverse"] = reverse
    for param in otherparams:
        content[param] = otherparams[param]
    rsp = session.get(url, params=content, headers=headers_tmp)
    return json.loads(str(rsp.content, 'utf-8'))

def getTorrentPeers(root_url, session, tro_hash, rid):
    url = root_url + '/api/v2/sync/torrentPeers'
    headers_tmp = headers.copy()
    headers_tmp['Accept'] = 'application/json'
    headers_tmp['Accept-Encoding'] = 'gzip, deflate, br'
    content = {'hash':tro_hash, 'rid': rid}
    rsp = session.get(url, params=content, headers=headers_tmp)
    return json.loads(str(rsp.content, 'utf-8'))

def readconf(conf_path):
    with open(conf_path,mode='r') as conf_file:
        for line in conf_file:
            if line[0] == '#':
                continue
            match = re.match("([\w ]+?)=",line)
            if match is None:
                continue
            key = match.group(1).strip()
            if key not in conf:
                continue
            value = re.search("=(\S+)",line)
            if value is not None:
                value = value.group(1).strip()
                if key == "block":
                    value = re.match("(\S+?),(\S+)",value)
                    if value is not None:
                        conf[key].append({"str":value.group(1),"type":value.group(2)})
                else:
                    conf[key] = value
    

def reloadIpFilter(root_url, session):
    url = root_url + '/api/v2/app/setPreferences'
    reload = {'ip_filter_enabled': True}
    content = {'json': json.dumps(reload, ensure_ascii=False)}
    session.post(url, content, headers=headers)


def isNeedBlockClient(peer):
    client = peer.get('client')
    if client is None:
        return False

    for deFilter in conf["block"]:
        if int(deFilter['type']) == 1 and client.find(deFilter['str']) > -1:
            return True
        elif int(deFilter['type']) == 2 and client.startswith(deFilter['str']):
            return True

    return False

def login(root_url, session, username, password):
    url = root_url + '/api/v2/auth/login'
    response = session.post(url, {"username":username, "password":password}, headers=headers)
    return response.text

def blocking(conf_path):
    #read conf file to confdict
    readconf(conf_path)
    #the rid for the session
    rid = newrid()
    #the funcs are writen like root_url+api_url
    root_url = "http://"+conf["ip"]+":"+conf["port"]

    session = requests.session()
    
    #login
    if login(root_url, session, conf["username"], conf["password"]) != 'Ok.':
        exit(0)

    #set block ip
    blocked_ips = {} #like {"ip":None}
    with open(conf["ipdat_path"],mode='r') as file_ips:
        for line in file_ips:
            match = re.match("([^\-]+?)-",line)
            if match is not None:
                blocked_ips[match.group(1).strip()] = None
    print("There have been "+str(len(blocked_ips))+" ips filtered")
    newblock_ips = {} 
    print("The block ip set:" + str(conf["block"]))
    #scaning
    print("begin scan torrents")
    while True:
        #get a torrentlist that sorted by upspeed from large to small for finding xunlei
        tor_list = getTorrentList(root_url, session, rid, tor_filter="active", sort="upspeed")
        #print("there is " + str(len(tor_list)) + " torrents active now")

        for tor in tor_list:
            #the peersinfo is like { "some":some, "peers":{"ip:port":{"client":wanted,"upspeed":value}}}
            peersinfo = getTorrentPeers(root_url, session, tor["hash"], rid)
            if "peers" not in peersinfo:
                continue
            for v in peersinfo["peers"].values():
                if (v['ip'] not in blocked_ips) and isNeedBlockClient(v):
                    print("find "+ v["client"] + " at " + v["ip"] + ". added")
                    newblock_ips[v['ip']] = None
            time.sleep(1)
        
        #refresh new block in file and apply
        if len(newblock_ips) > 0:
            ip_str = ""
            for newip in newblock_ips:
                ip_str = ip_str + newip + '-' + newip + ' , 127 , banxunlei\n'
                blocked_ips[newip] = None
            print("refresh added list")
            with open(conf['ipdat_path'],mode='a+') as file_ips:
                file_ips.write(ip_str)
            reloadIpFilter(root_url, session)
            newblock_ips.clear()

        time.sleep(10)
    
    
if __name__ == "__main__":
    import argparse
    import os
    parser = argparse.ArgumentParser(description='ban specific clients for qbitorrent')
    parser.add_argument('-c','--conf', help='conf file path')
    args = parser.parse_args()
    conf_path = vars(args).get('conf')
    if (conf_path is not None) and os.access(conf_path, os.R_OK):
        blocking(conf_path)
    elif os.access('bx.conf',os.R_OK):
        blocking('bx.conf')
    else:
        print("not found conf file")


