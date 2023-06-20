import datetime
import random
import re
import time
from urllib.parse import urlencode
from urllib.parse import urlparse

import requests

from Parameter import MsToken
from Parameter import TtWid
from Parameter import XBogus
from Recorder import RunLogger
from StringCleaner import Cleaner


def sleep():
    """避免频繁请求"""
    time.sleep(random.randrange(10, 40, 5) * 0.1)


def reset(function):
    """重置数据"""

    def inner(self, *args, **kwargs):
        if not isinstance(self.url, bool):
            self.id_ = None
        self.max_cursor = 0
        self.list = None  # 未处理的数据
        self.name = None  # 账号昵称
        self.video_data = []  # 视频ID数据
        self.image_data = []  # 图集ID数据
        self.finish = False  # 是否获取完毕
        return function(self, *args, **kwargs)

    return inner


def check_cookie(function):
    """检查是否设置了Cookie"""

    def inner(self, *args, **kwargs):
        if self.cookie:
            return function(self, *args, **kwargs)
        print("未设置Cookie！")
        return False

    return inner


def retry(max_num=3):
    """发生错误时尝试重新执行"""

    def inner(function):
        def execute(self, *args, **kwargs):
            for i in range(max_num):
                if r := function(self, *args, **kwargs):
                    return r

        return execute

    return inner


class UserData:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36",
        'referer': 'https://www.douyin.com/',
    }
    share = re.compile(
        r".*?(https://v\.douyin\.com/[A-Za-z0-9]+?/).*?")  # 分享短链
    account_link = re.compile(
        r"^https://www\.douyin\.com/user/([a-zA-z0-9-_]+)(?:\?modal_id=([0-9]{19}))?.*$")  # 账号链接
    works_link = re.compile(
        r"^https://www\.douyin\.com/(?:video|note)/([0-9]{19})$")  # 作品链接
    live_link = re.compile(r"^https://live\.douyin\.com/([0-9]+)$")  # 直播链接
    live_api = "https://live.douyin.com/webcast/room/web/enter/"  # 直播API
    clean = Cleaner()  # 过滤非法字符

    def __init__(self, log: RunLogger):
        self.xb = XBogus()  # 加密参数对象
        self.log = log  # 日志记录对象
        self._cookie = False  # 是否设置了Cookie
        self.id_ = None  # sec_uid or item_ids
        self.max_cursor = 0
        self.list = None  # 未处理的数据
        self.name = None  # 账号昵称
        self.video_data = []  # 视频ID数据
        self.image_data = []  # 图集ID数据
        self.finish = False  # 是否获取完毕
        self._earliest = None  # 最早发布时间
        self._latest = None  # 最晚发布时间
        self._url = None  # 账号链接
        self._api = None  # 批量下载类型
        self._proxies = None  # 代理

    @property
    def url(self):
        return self._url

    @url.setter
    def url(self, value):
        if self.share.match(value):
            self._url = value
            self.log.info(f"当前账号链接: {value}", False)
        elif len(s := self.account_link.findall(value)) == 1:
            self._url = True
            self.id_ = s[0][0]
            self.log.info(f"当前账号链接: {value}", False)
        else:
            self.log.warning(f"无效的账号链接: {value}")

    @property
    def api(self):
        return self._api

    @api.setter
    def api(self, value):
        if value in ("post", "favorite"):
            self._api = f"https://www.douyin.com/aweme/v1/web/aweme/{value}/"
        else:
            self.log.warning(f"批量下载类型错误！必须设置为“post”或者“favorite”，错误值: {value}")

    @property
    def cookie(self):
        return self._cookie

    @cookie.setter
    def cookie(self, cookie: str | tuple):
        if not cookie:
            return
        elif isinstance(cookie, str):
            self.headers["Cookie"] = cookie
            self._cookie = True
        elif isinstance(cookie, tuple):
            for i in cookie:
                self.headers["Cookie"] += f"; {i}"
            self._cookie = True

    @property
    def earliest(self):
        return self._earliest

    @earliest.setter
    def earliest(self, value):
        if not value:
            self._earliest = datetime.date(2016, 9, 20)
            return
        try:
            self._earliest = datetime.datetime.strptime(
                value, "%Y/%m/%d").date()
            self.log.info(f"作品最早发布日期: {value}")
        except ValueError:
            self.log.warning("作品最早发布日期无效！")

    @property
    def latest(self):
        return self._latest

    @latest.setter
    def latest(self, value):
        if not value:
            self._latest = datetime.date.today()
            return
        try:
            self._latest = datetime.datetime.strptime(value, "%Y/%m/%d").date()
            self.log.info(f"作品最晚发布日期: {value}")
        except ValueError:
            self.log.warning("作品最晚发布日期无效！")

    @property
    def proxies(self):
        return self._proxies

    @proxies.setter
    def proxies(self, value):
        if value and isinstance(value, str):
            test = {
                "http": value,
                "https": value,
            }
            try:
                response = requests.get(
                    "http://httpbin.org/", proxies=test, timeout=15)
                if response.status_code == 200:
                    self.log.info("代理测试通过！")
                    self._proxies = test
                    return
            except requests.exceptions.ReadTimeout:
                self.log.warning("代理测试超时！")
            except requests.exceptions.ProxyError:
                self.log.warning("代理测试失败！")
        self._proxies = {
            "http": None,
            "https": None,
        }

    @retry(max_num=5)
    def get_id(self, value="sec_uid", url=None):
        """获取账号ID或者作品ID"""
        if self.id_:
            self.log.info(f"{url} {value}: {self.id_}", False)
            return True
        url = url or self.url
        try:
            response = requests.get(
                url,
                headers=self.headers,
                proxies=self.proxies,
                timeout=10)
        except requests.exceptions.ReadTimeout:
            return False
        sleep()
        if response.status_code == 200:
            params = urlparse(response.url)
            self.id_ = params.path.rstrip("/").split("/")[-1]
            self.log.info(f"{url} {value}: {self.id_}", False)
            return True
        else:
            self.log.error(
                f"{url} 响应码异常：{response.status_code}，获取 {value} 失败！")
            return False

    def deal_params(self, params: dict) -> dict:
        xb = self.xb.get_x_bogus(urlencode(params))
        params["X-Bogus"] = xb
        return params

    @retry(max_num=5)
    def get_user_data(self):
        """获取账号作品信息"""
        params = {
            "aid": "6383",
            "sec_user_id": self.id_,
            "count": "35",
            "max_cursor": self.max_cursor,
            "cookie_enabled": "true",
            "platform": "PC",
            "downlink": "10",
        }
        params = self.deal_params(params)
        try:
            response = requests.get(
                self.api,
                params=params,
                headers=self.headers,
                proxies=self.proxies,
                timeout=10)
        except requests.exceptions.ReadTimeout:
            print("请求超时！")
            return False
        sleep()
        if response.status_code == 200:
            try:
                data = response.json()
            except requests.exceptions.JSONDecodeError:
                self.list = []
                self.log.error("数据接口返回内容异常！疑似接口失效！", False)
                return False
            try:
                self.max_cursor = data['max_cursor']
                self.list = data["aweme_list"]
                return True
            except KeyError:
                self.list = []
                self.log.error(f"响应内容异常: {data}", False)
                return False
        else:
            self.list = []
            self.log.error(f"响应码异常：{response.status_code}，获取JSON数据失败！")
            return False

    def deal_data(self):
        """对账号作品进行分类"""
        if len(self.list) == 0:
            self.log.info("该账号的资源信息获取结束！")
            self.finish = True
        else:
            self.name = self.clean.filter(self.list[0]["author"]["nickname"])
            for item in self.list:
                if t := item["aweme_type"] == 68:
                    self.image_data.append(
                        [item["create_time"], item["aweme_id"]])
                elif t == 0:
                    self.video_data.append(
                        [item["create_time"], item["aweme_id"]])
                else:
                    self.log.warning(f"无法判断资源类型, 详细数据: {item}")

    def summary(self):
        """汇总账号作品数量"""
        self.log.info(f"账号 {self.name} 的视频总数: {len(self.video_data)}")
        for i in self.video_data:
            self.log.info(f"视频: {i[1]}", False)
        self.log.info(f"账号 {self.name} 的图集总数: {len(self.image_data)}")
        for i in self.image_data:
            self.log.info(f"图集: {i[1]}", False)

    @reset
    @check_cookie
    def run(self, index: int):
        """批量下载模式"""
        if not all(
                (self.api,
                 self.url,
                 self.earliest,
                 self.latest,
                 self.cookie)):
            self.log.warning("请检查账号链接、批量下载类型、最早发布时间、最晚发布时间、Cookie是否正确！")
            return False
        self.log.info(f"正在获取第 {index} 个账号数据！")
        self.get_id()
        if not self.id_:
            self.log.error("获取账号 sec_uid 失败！")
            return False
        while not self.finish:
            self.get_user_data()
            self.deal_data()
        if not self.name:
            self.log.error("获取账号数据失败，请稍后重试！")
            return False
        self.date_filters()
        self.summary()
        self.log.info(f"获取第 {index} 个账号数据成功！")
        return True

    @reset
    @check_cookie
    def run_alone(self, text: str):
        """单独下载模式"""
        if not self.cookie:
            self.log.warning("请检查Cookie是否正确！")
            return False
        url = self.check_url(text)
        if not url:
            self.log.warning("无效的作品链接！")
            return False
        self.get_id("item_ids", url)
        return self.id_ or False

    def check_url(self, url: str):
        if len(s := self.works_link.findall(url)) == 1:
            self.id_ = s[0]
            return url
        elif len(s := self.share.findall(url)) == 1:
            return s[0]
        elif len(s := self.account_link.findall(url)) == 1:
            if s := s[0][1]:
                self.id_ = s
                return url
        return False

    def date_filters(self):
        """筛选发布时间"""
        earliest_date = self.earliest
        latest_date = self.latest
        filtered = []
        for item in self.video_data:
            date = datetime.datetime.fromtimestamp(item[0]).date()
            if earliest_date <= date <= latest_date:
                filtered.append(item[1])
        self.video_data = filtered
        filtered = []
        for item in self.image_data:
            date = datetime.datetime.fromtimestamp(item[0]).date()
            if earliest_date <= date <= latest_date:
                filtered.append(item[1])
        self.image_data = filtered

    def get_live_id(self, link: str):
        """检查直播链接并返回直播ID"""
        return s[0] if len(s := self.live_link.findall(link)) == 1 else None

    def add_cookie(self):
        mstoken = MsToken.get_ms_token()
        ttwid = TtWid.get_TtWid()
        self.cookie = (mstoken, ttwid)

    @check_cookie
    def get_live_data(self, link: str):
        id_ = self.get_live_id(link)
        if not id_:
            self.log.warning("直播链接格式错误！")
            return False
        self.add_cookie()
        params = {
            "aid": "6383",
            "device_platform": "web",
            "web_rid": id_
        }
        params = self.deal_params(params)
        try:
            response = requests.get(
                self.live_api,
                headers=self.headers,
                params=params,
                timeout=10,
                proxies=self.proxies)
            return response.json()
        except requests.exceptions.ReadTimeout:
            print("请求超时！")
            return False
        except requests.exceptions.JSONDecodeError:
            self.log.warning("直播数据接口返回内容格式错误！")
            return False

    def deal_live_data(self, data):
        if data["data"]["data"][0]["status"] == 4:
            self.log.info("当前直播已结束！")
            return None
        nickname = self.clean.filter(
            data["data"]["data"][0]["owner"]["nickname"])
        title = self.clean.filter(data["data"]["data"][0]["title"])
        url = data["data"]["data"][0]["stream_url"]["flv_pull_url"]
        return nickname, title, url
