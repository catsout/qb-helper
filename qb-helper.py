import json
import random
import logging
import asyncio
import aiohttp
import aiofiles
import os
import subprocess
import base64
from datetime import date
from typing import Any,TypeVar,Optional,Awaitable,Callable
from types import SimpleNamespace

import dataclasses
from dataclasses import dataclass
from dataclasses_json import dataclass_json

from copy import deepcopy

logger = logging.getLogger('qbt-helper')
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)

T = TypeVar('T')

@dataclass_json
@dataclass
class Config:
    host: str = 'localhost'
    port: int = 8080
    username: str = 'admin'
    password: str = 'adminadmin'
    refresh_day: int = 0
    tls: bool = False
    block: list[str] = dataclasses.field(default_factory=list)
    fifo: str = ''
    complete_exe: str = ''

@dataclass_json
@dataclass
class QbPreferences:
    ip_filter_enabled: bool
    ip_filter_path: str
    banned_ips: list[str]

@dataclass_json
@dataclass
class Torrent:
    name: str
    infohash_v1: str
    category: str
    state: str
    save_path: str

@dataclass_json
@dataclass
class Peer:
    ip: str
    port: int
    client: str
    country_code: str
    up_speed: int

@dataclass_json
@dataclass
class PeersInfo:
    rid: int = 0
    peers: dict[str, Peer] = dataclasses.field(default_factory=dict)
    peers_removed: list[str] = dataclasses.field(default_factory=list)

@dataclass_json
@dataclass
class QbMaindata:
    rid: int = 0
    torrents: dict[str,Torrent] = dataclasses.field(default_factory=dict)
    torrents_removed: list[str] = dataclasses.field(default_factory=list)

@dataclass
class GlobalData:
    maindata: QbMaindata = dataclasses.field(default_factory=QbMaindata)

def deep_merge(a: dict, b: dict) -> dict:
    result = deepcopy(a)
    for bk, bv in b.items():
        av = result.get(bk)
        if isinstance(av, dict) and isinstance(bv, dict):
            result[bk] = deep_merge(av, bv)
        else:
            result[bk] = deepcopy(bv)
    return result

def interval(t: int, trigger: Callable[[], Awaitable[None]]):
    async def run():
        while True:
            await trigger()
            await asyncio.sleep(t)
    return asyncio.create_task(run())

class QbAPI:
    header_json = {
        'Accept': 'application/json',
        'Accept-Encoding':'gzip, deflate, br'
    }
    def __init__(self, root_url: str):
        self.rid = self.newrid()
        self.root_url = root_url
        jar = aiohttp.CookieJar(unsafe=True)
        self.session = aiohttp.ClientSession(cookie_jar=jar)
        self.session.headers.update({
            'Accept': 'text/javascript, text/html, application/xml, text/xml, */*',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'User-Agent': 'curl/7.72.0'
        })

    async def close(self):
        await self.session.close()

    def newrid(self) -> int:
        return int(random.random()*1000)
    
    async def get_maindata(self, pre: QbMaindata) -> QbMaindata:
        url = f'{self.root_url}/api/v2/sync/maindata'
        content = {'rid': pre.rid}
        rsp = await self.session.get(url, params=content, headers=self.header_json)
        d: dict = deep_merge(pre.to_dict(), await rsp.json())
        maindata = QbMaindata.from_dict(d)
        for t in maindata.torrents_removed:
            if t in maindata.torrents:
                maindata.torrents.pop(t)
        maindata.torrents_removed.clear()
        return maindata

    # filter: all, downloading, seeding, completed, paused, active, inactive, resumed, stalled, stalled_uploading, stalled_downloading, errored 
    # sort: size upspeed downspeed ratio
    async def get_torrent_list(self,reverse: bool, tor_filter:Optional[str], sort:Optional[str], otherparams: Optional[dict[str, Any]]) -> list[Torrent]:
        url = f'{self.root_url}/api/v2/torrents/info'
        content: dict[str, Any] = {'rid': self.rid}
        if tor_filter is not None:
            content['filter'] = tor_filter
        if sort is not None:
            content['sort'] = sort
        content['reverse'] = str(reverse)
        if otherparams is not None:
            for param in otherparams:
                content[param] = otherparams[param]
        rsp = await self.session.get(url, params=content, headers=self.header_json)
        tors = await rsp.json()
        return map(lambda t: Torrent.from_dict(t), tors)
    
    async def get_torrent_peers(self, hash: str, peers: PeersInfo) -> PeersInfo:
        url = f'{self.root_url}/api/v2/sync/torrentPeers'
        content = {'hash':hash, 'rid': peers.rid}
        rsp = await self.session.get(url, params=content, headers=self.header_json)
        d: dict = deep_merge(peers.to_dict(), await rsp.json())
        peers = PeersInfo.from_dict(d)
        for p in peers.peers_removed:
            if p in peers.peers:
                peers.peers.pop(p)
        peers.peers_removed.clear()
        return peers

    async def ban_peers(self, ip_port_list: list[str]):
        url = f'{self.root_url}/api/v2/transfer/banPeers'
        data = {'peers': '|'.join(ip_port_list)}
        await self.session.post(url, data=data)

    async def get_preferences(self) -> QbPreferences:
        url = f'{self.root_url}/api/v2/app/preferences'
        rsp = await self.session.get(url)
        rsp_j = await rsp.json()
        banned_IPs: str = rsp_j.get('banned_IPs') or ''
        rsp_j['banned_ips'] = banned_IPs.splitlines()
        return QbPreferences.from_dict(rsp_j)

    async def set_preferences(self, configs: dict[str, Any]):
        url = f'{self.root_url}/api/v2/app/setPreferences'
        data = {'json': json.dumps(configs, ensure_ascii=False)}
        await self.session.post(url, data=data)

    async def set_autorun_program(self, cmd: str):
        await self.set_preferences({'autorun_enabled': True, 'autorun_program': cmd})

    async def set_banned_ips(self, ips: list[str]):
        await self.set_preferences({'banned_IPs': ips})

    async def set_ip_filter_path(self, path: str):
        await self.set_preferences({'ip_filter_path': path})

    async def set_ip_filter_enabled(self, val: bool):
        await self.set_preferences({'ip_filter_enabled': val})
    
    async def login(self, username: str, password: str) -> bool: 
        url = f'{self.root_url}/api/v2/auth/login'
        rsp = await self.session.post(url, data={'username':username, 'password':password})
        return await rsp.text() == 'Ok.'

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
    
def is_block_client(cfg: Config, peer: Peer) -> bool:
    for bc in cfg.block:
        if peer.client.find(bc) != -1:
            return True
    return False

async def monitor_fifo(cfg: Config, g: GlobalData):
    fifo = cfg.fifo
    exe = cfg.complete_exe

    async def fifo_callback(line: str):
        logger.info(f'torrent {line} complete, trigger complete program')
        tor = g.maindata.torrents.get(line)
        if tor:
            tor_d: dict = tor.to_dict()
            tor_bs = json.dumps(tor_d, ensure_ascii=False).encode('UTF-8')
            tor_str = base64.b64encode(tor_bs).decode('ascii')
            proc = await asyncio.create_subprocess_exec(exe, tor_str, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)

            async def log_proc():
                stdout,_ = await proc.communicate()
                output = stdout.strip().decode('utf-8')
                logger.info(f'subprocess output: {output}')
                logger.info(f'subprocess end')

            asyncio.create_task(log_proc())

    if not fifo or not exe:
        return
    if os.path.exists(fifo):
        os.unlink(fifo)
    os.mkfifo(fifo)

    async with aiofiles.open(fifo, mode='r') as f:
        while True:
            async for line in f:
                await fifo_callback(line)

async def qb_update(cfg: Config, qb_api: QbAPI, g: GlobalData):
    if not await qb_api.login(cfg.username, cfg.password):
        logger.warning('login failed')
        return
    
    preferences = await qb_api.get_preferences()
    logger.info(f'Load {len(preferences.banned_ips)} blocked ips')
    logger.info(f'Blocked clients: {cfg.block}')

    newblock_ips: set[str] = set()
    vars = SimpleNamespace(lasttime=date.today(), peersinfo=PeersInfo())
    
    # first run
    g.maindata = await qb_api.get_maindata(g.maindata)
    if cfg.fifo:
        await qb_api.set_autorun_program(f'''/usr/bin/bash -c "echo -n %I > {cfg.fifo}"''')

    async def blocking():
        for tor in g.maindata.torrents.values():
            vars.peersinfo = await qb_api.get_torrent_peers(tor.infohash_v1, vars.peersinfo)
            for ip_port,peer in vars.peersinfo.peers.items():
                if is_block_client(cfg, peer):
                    newblock_ips.add(ip_port)

        if len(newblock_ips) > 0:
            await qb_api.ban_peers(list(newblock_ips))
            newblock_ips.clear()

        nowtime = date.today()
        re_internal = cfg.refresh_day
        if re_internal > 0 and (nowtime - vars.lasttime).days > re_internal:
            logger.info('refresh blocked ip')
            await qb_api.set_banned_ips([])
            vars.lasttime = nowtime

    async def update_maindata():
        g.maindata = await qb_api.get_maindata(g.maindata)

    await asyncio.gather(
        interval(3, update_maindata),
        interval(30, blocking),
        monitor_fifo(cfg, g)
    )

async def start(cfg: Config):
    gdata = GlobalData()
    url = f'http{"s" if cfg.tls else ""}://{cfg.host}:{cfg.port}'
    api = QbAPI(url);
    logger.info(f'connect to {url}')
    while(True):
        try:
            await qb_update(cfg, api, gdata)
        except aiohttp.ClientError as err:
            logger.exception(err)

        logger.debug('sleep 30s')
        await asyncio.sleep(30)
        # await api.close()
     
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='ban specific clients for qbitorrent')
    parser.add_argument('-a','--host', help='WebUI host')
    parser.add_argument('-p','--port', help='WebUI port')
    parser.add_argument('--username', help='WebUI username')
    parser.add_argument('--password', help='WebUI password')
    parser.add_argument('--refresh-day', type=int, help='internal(day) of refreshing blocked ips')
    parser.add_argument('--block', action='append', help='blocked client')
    parser.add_argument('--tls', action='store_true', help='enable tls')
    parser.add_argument('--fifo', help='fifo pipe path, needed for torrent completion')
    parser.add_argument('--complete-exe', help='program to run when torrent complete, argurment is base64 of json')

    args = vars(parser.parse_args())
    args = {k.replace('-', '_'):v for k,v in args.items() if v is not None}
    config = Config.from_dict(args)
    logger.debug(config)
    asyncio.run(start(config))
