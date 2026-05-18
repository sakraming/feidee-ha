"""
飞蛋记账 (Feidee) Web API 完整调用示例
=========================================

本脚本演示了通过逆向工程获得的所有飞蛋 Web API 的调用方式，包括：
  - 账号密码登录（自动管理 token）
  - 列出所有账本
  - 拉取交易明细（自动翻页）
  - 拉取分类汇总统计（支持按月/日/周/年聚合）
  - 拉取分类树
  - 拉取账户列表与余额
  - 获取用户信息

跑一遍这个脚本，你会看到所有接口的返回数据结构。
基于此可以开发任何上层应用（HA 集成、Agent Skill、CLI 工具等）。

依赖：
    pip install httpx

使用：
    1. 修改下面 PHONE 和 PASSWORD 为你的飞蛋账号
    2. python feidee_demo.py
"""

import asyncio
import hashlib
import json
import random
import time
from datetime import datetime
from typing import Optional

import httpx

# ============================================================================
# 配置区（用户需要修改）
# ============================================================================

PHONE = "你的手机号"           # 例如 "13800138000"
PASSWORD = "你的飞蛋密码明文"   # SDK 内部会做 SHA1

# ============================================================================
# 飞蛋 API 常量（逆向工程获得，不要修改）
# ============================================================================

# 业务接口签名密钥（用于 yun.feidee.net 下所有接口）
BIZ_CLIENT_KEY = "PiVEoJM9OHFS8xFlnD3CuSrJgRgyVLwS"
BIZ_SECRET = "pQhGxs0I84zQgeU8"

# 登录/认证接口签名密钥（用于 auth.feidee.net / userapi.feidee.net）
LOGIN_CLIENT_KEY = "520BFC1EA31D45678A9B865668A47F40"
LOGIN_SECRET = ""  # 注意：登录系统的 secret 是空字符串

# 域名
AUTH_BASE = "https://auth.feidee.net"
USER_BASE = "https://userapi.feidee.net"
YUN_BASE = "https://yun.feidee.net"

# 模拟的设备信息（device_id 建议持久化，每个客户端固定一个）
DEVICE_JSON = json.dumps({
    "model": "os",
    "platform": "MacIntel",
    "os_version": "",
    "device_id": "fed-8e89c1f1-183f-4829-8c95-179232e50a02",
    "product_name": "cab-web",
    "product_version": "148.0.0.0",
    "locale": "zh-CN",
    "time_zone": "Asia/Shanghai",
}, separators=(',', ':'))

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)


# ============================================================================
# 签名 & Headers 生成
# ============================================================================

def _gen_sign(client_key: str, secret: str) -> tuple[str, str, str]:
    """生成 (nonce, timestamp, sign)
    
    签名算法：MD5(client_key + nonce + timestamp + secret)
    """
    nonce = str(random.randint(0, 10**16)).zfill(16)
    timestamp = str(int(time.time() * 1000))
    raw = client_key + nonce + timestamp + secret
    sign = hashlib.md5(raw.encode()).hexdigest()
    return nonce, timestamp, sign


def gen_login_headers() -> dict:
    """生成登录/认证接口的 Headers"""
    nonce, ts, sign = _gen_sign(LOGIN_CLIENT_KEY, LOGIN_SECRET)
    return {
        "App-Id": "cab-web",
        "Type": "MD5-H5",
        "Minor-Version": "2",
        "Client-Key": LOGIN_CLIENT_KEY,
        "Nonce-Str": nonce,
        "Timestamp": ts,
        "Sign": sign,
        "Content-Type": "application/json",
        "Device": DEVICE_JSON,
        "Origin": "https://www.feidee.com",
        "Referer": "https://www.feidee.com/",
        "User-Agent": USER_AGENT,
    }


def gen_business_headers(
    access_token: str,
    trading_entity: Optional[str] = None,
) -> dict:
    """生成业务接口的 Headers
    
    Args:
        access_token: 登录后获得的 access_token（不含 'Bearer ' 前缀）
        trading_entity: 账本 ID。某些接口（如列账本）不需要传
    """
    nonce, ts, sign = _gen_sign(BIZ_CLIENT_KEY, BIZ_SECRET)
    headers = {
        "Client-Key": BIZ_CLIENT_KEY,
        "Nonce-Str": nonce,
        "Timestamp": ts,
        "Sign": sign,
        "Authorization": f"Bearer {access_token}",
        "Device": DEVICE_JSON,
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.feidee.com",
        "Referer": "https://www.feidee.com/",
        "User-Agent": USER_AGENT,
    }
    if trading_entity:
        headers["Trading-Entity"] = trading_entity
    return headers


# ============================================================================
# 认证 API
# ============================================================================

async def login(client: httpx.AsyncClient, phone: str, password: str) -> dict:
    """账号密码登录
    
    密码必须是 SHA1 后的小写十六进制字符串。
    
    返回：
        {
            "access_token": "uuid-format",
            "refresh_token": "uuid-format",  # 注意：飞蛋实际无 refresh 机制，此字段是摆设
            "scope": "user",
            "token_type": "Bearer",
            "expires_in": 2591999992  # 约 30 天（疑似毫秒单位）
        }
    
    重要：
        - 飞蛋没有真正的 refresh_token 机制
        - access_token 过期时应该用密码重新登录
    """
    password_sha1 = hashlib.sha1(password.encode()).hexdigest()
    
    params = {
        "grant_type": "password_web",
        "encode_version": "V4",
        "scope": "user",
        "username": phone,
        "password": password_sha1,
        "vcid": "",
        "vid": "",
    }
    
    r = await client.get(
        f"{AUTH_BASE}/v2/oauth2/authorize",
        params=params,
        headers=gen_login_headers(),
    )
    r.raise_for_status()
    return r.json()


async def logout(client: httpx.AsyncClient, access_token: str) -> None:
    """注销登录（撤销 token）"""
    headers = gen_login_headers()
    headers["Authorization"] = f"Bearer {access_token}"
    
    await client.delete(
        f"{AUTH_BASE}/v2/revocation/tokens/self",
        headers=headers,
    )


async def get_user_profile(client: httpx.AsyncClient, access_token: str) -> dict:
    """获取当前用户信息"""
    headers = gen_login_headers()
    headers["Authorization"] = f"Bearer {access_token}"
    
    r = await client.get(
        f"{USER_BASE}/v1/profile",
        headers=headers,
    )
    r.raise_for_status()
    return r.json()


# ============================================================================
# 业务 API
# ============================================================================

async def list_books(client: httpx.AsyncClient, access_token: str) -> list[dict]:
    """列出当前用户的所有账本（云端账本）
    
    返回结构示例：
        [
            {
                "id": "1076886133258780672",    # 账本 ID（即 Trading-Entity）
                "name": "我家账本",
                "icon": {"url": "..."},
                "cover": {"url": "..."},
                "created_time": "1763536861000",
                "creator": {...},
                "role_list": ["maintainer"]
            }
        ]
    """
    r = await client.get(
        f"{YUN_BASE}/cab-index-ws/v3/book-group/cloud",
        headers=gen_business_headers(access_token),  # 注意：不传 trading_entity
    )
    r.raise_for_status()
    return r.json().get("cloud_book_list", [])


async def get_transactions_page(
    client: httpx.AsyncClient,
    access_token: str,
    book_id: str,
    month: str,
    page_offset: int = 0,
    page_size: int = 100,
) -> dict:
    """拉取交易明细的单页
    
    Args:
        book_id: 账本 ID
        month: 月份，格式 "YYYYMM"，例如 "202605"
        page_offset: 偏移量
        page_size: 每页数量，最大 100
    
    返回：
        {
            "data": [...],
            "paging": {"has_more": bool, "page_offset": int, "page_size": int}
        }
    
    单条 transaction 关键字段：
        - id, business_type (Expense/Income/Balance_Changed/Transfer)
        - amount, transaction_time (ms timestamp)
        - category.name, account.name, member.name, remark
    """
    body = {
        "group_filter": {"group_key": "TIME_MONTH", "group_id": month},
        "query": {},
        "sort": {"order_by": "DESC", "sort_by": "ACCOUNT_TIME"},
        "page": {"page_offset": page_offset, "page_size": page_size},
    }
    
    r = await client.post(
        f"{YUN_BASE}/cab-query-ws/v2/statistics/transactions",
        json=body,
        headers=gen_business_headers(access_token, trading_entity=book_id),
    )
    r.raise_for_status()
    return r.json()


async def get_all_transactions(
    client: httpx.AsyncClient,
    access_token: str,
    book_id: str,
    month: str,
) -> list[dict]:
    """拉取某月全部交易明细（自动翻页）"""
    all_data = []
    offset = 0
    page_size = 100
    
    while True:
        result = await get_transactions_page(
            client, access_token, book_id, month, offset, page_size
        )
        data = result.get("data", [])
        all_data.extend(data)
        
        if not result.get("paging", {}).get("has_more", False):
            break
        offset += page_size
        await asyncio.sleep(0.3)  # 礼貌延迟
    
    return all_data


async def get_rollup_summary(
    client: httpx.AsyncClient,
    access_token: str,
    book_id: str,
    group_key: str = "TIME_MONTH",
    group_id: Optional[str] = None,
    category_type: str = "Expense",
    group_by: str = "CATEGORY_SECOND",
) -> dict:
    """获取分类汇总统计（核心统计接口）
    
    Args:
        group_key: 时间维度
            - "TIME_MONTH" → "202605"
            - "TIME_DAY"   → "20260518"
            - "TIME_WEEK"  → "2026_20"
            - "TIME_YEAR"  → "2026"
        group_id: 对应 group_key 的值。不传 = 全部时间
        category_type: "Expense" / "Income"
        group_by: 分组方式
            - "CATEGORY_FIRST"  → 一级分类
            - "CATEGORY_SECOND" → 二级分类
            - "ACCOUNT"         → 按账户
            - "MEMBER"          → 按成员
    
    返回：
        {
            "metric_data": [
                {"key": "INCOME", "value": "0.00", "label": "收入"},
                {"key": "EXPENSE", "value": "44323.50", "label": "支出"},
                {"key": "BALANCE", "value": "-44323.50", "label": "结余"},
                ...
            ],
            "data": [...]  # 每个分组的详细数据
        }
    """
    body = {
        "group": {"group_by": group_by, "show_all": False},
        "query": {
            "exclude_null_category": True,
            "category_types": [category_type],
        },
        "sort": {"order_by": "DESC", "sort_by": "GROUP_ID"},
    }
    if group_id:
        body["group_filter"] = {"group_key": group_key, "group_id": group_id}
    
    r = await client.post(
        f"{YUN_BASE}/cab-query-ws/v2/statistics/rollup-groups",
        json=body,
        headers=gen_business_headers(access_token, trading_entity=book_id),
    )
    r.raise_for_status()
    return r.json()


async def get_categories(
    client: httpx.AsyncClient,
    access_token: str,
    book_id: str,
    trade_type: str = "Expense",
) -> list[dict]:
    """获取分类树（含父子层级关系）
    
    Args:
        trade_type: "Expense" / "Income"
    
    返回：嵌套结构，每个分类的 sub_categories 是子分类列表
    """
    r = await client.get(
        f"{YUN_BASE}/cab-config-ws/v2/account-book/categories",
        params={"trade_type": trade_type},
        headers=gen_business_headers(access_token, trading_entity=book_id),
    )
    r.raise_for_status()
    return r.json().get("data", [])


async def get_accounts(
    client: httpx.AsyncClient,
    access_token: str,
    book_id: str,
) -> list[dict]:
    """获取账户列表（含余额）
    
    返回：账户按类型分组的列表
        [
            {
                "id": "1",
                "name": "现金账户",
                "amount": "19729.27",  # 该类型总余额
                "accounts": [  # 子账户列表
                    {
                        "id": "...",
                        "name": "农行黑金0004",
                        "balance": "8090.00",
                        "type": "Cash",
                        "currency": {"symbol": "￥", "code": "CNY"},
                    }
                ]
            }
        ]
    """
    r = await client.get(
        f"{YUN_BASE}/cab-config-ws/v2/account-book/accounts",
        params={"scene": "Common"},
        headers=gen_business_headers(access_token, trading_entity=book_id),
    )
    r.raise_for_status()
    return r.json().get("data", [])


# ============================================================================
# 高级封装：带自动重登的客户端（推荐使用方式）
# ============================================================================

class FeideeClient:
    """飞蛋客户端：支持自动管理 token，过期自动重登"""
    
    def __init__(self, phone: str, password: str):
        self.phone = phone
        self.password = password
        self.access_token: Optional[str] = None
        self._http = httpx.AsyncClient(timeout=30.0)
    
    async def __aenter__(self):
        await self.login()
        return self
    
    async def __aexit__(self, *args):
        await self._http.aclose()
    
    async def login(self) -> None:
        """登录并保存 token"""
        result = await login(self._http, self.phone, self.password)
        self.access_token = result["access_token"]
        print(f"✅ 登录成功: token={self.access_token[:20]}..., "
              f"过期时间: {result.get('expires_in')}ms")
    
    async def _call(self, func, *args, **kwargs):
        """统一调用入口，401 时自动重登"""
        if not self.access_token:
            await self.login()
        try:
            return await func(self._http, self.access_token, *args, **kwargs)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                print("⚠️ Token 失效，自动重新登录...")
                await self.login()
                return await func(self._http, self.access_token, *args, **kwargs)
            raise
    
    async def list_books(self):
        return await self._call(list_books)
    
    async def get_profile(self):
        return await self._call(get_user_profile)
    
    async def get_all_transactions(self, book_id: str, month: str):
        return await self._call(get_all_transactions, book_id, month)
    
    async def get_rollup_summary(self, book_id: str, **kwargs):
        return await self._call(get_rollup_summary, book_id, **kwargs)
    
    async def get_categories(self, book_id: str, trade_type: str = "Expense"):
        return await self._call(get_categories, book_id, trade_type)
    
    async def get_accounts(self, book_id: str):
        return await self._call(get_accounts, book_id)


# ============================================================================
# 演示：完整调用所有接口
# ============================================================================

def _preview(obj, max_len: int = 800) -> str:
    """打印对象的前几百字符预览"""
    s = json.dumps(obj, ensure_ascii=False, indent=2)
    return s if len(s) <= max_len else s[:max_len] + "\n... (省略)"


async def main():
    print("=" * 70)
    print("🚀 飞蛋记账 API 完整调用演示")
    print("=" * 70)
    
    async with FeideeClient(PHONE, PASSWORD) as client:
        
        # --- 1. 用户信息 ---
        print("\n" + "=" * 70)
        print("📌 1. 获取用户信息 (GET /v1/profile)")
        print("=" * 70)
        profile = await client.get_profile()
        print(_preview(profile))
        
        # --- 2. 账本列表 ---
        print("\n" + "=" * 70)
        print("📌 2. 列出所有账本 (GET /cab-index-ws/v3/book-group/cloud)")
        print("=" * 70)
        books = await client.list_books()
        print(f"共有 {len(books)} 个账本:")
        for b in books:
            print(f"  - [{b['id']}] {b['name']}")
        
        if not books:
            print("❌ 没有账本，退出")
            return
        
        # 选第一个账本做后续演示
        book_id = books[0]["id"]
        book_name = books[0]["name"]
        print(f"\n👉 使用账本「{book_name}」({book_id}) 做后续演示")
        
        # --- 3. 账户列表 ---
        print("\n" + "=" * 70)
        print("📌 3. 账户列表与余额 (GET /v2/account-book/accounts)")
        print("=" * 70)
        accounts = await client.get_accounts(book_id)
        print(f"共 {len(accounts)} 类账户:")
        for acc_group in accounts:
            print(f"\n  📁 {acc_group['name']} (总额: ¥{acc_group.get('amount', '0')})")
            for sub in acc_group.get("accounts", []):
                print(f"     - {sub['name']}: ¥{sub.get('balance', '0')} "
                      f"({sub.get('type', '?')})")
        
        # --- 4. 分类树 ---
        print("\n" + "=" * 70)
        print("📌 4. 支出分类树 (GET /v2/account-book/categories?trade_type=Expense)")
        print("=" * 70)
        exp_cats = await client.get_categories(book_id, "Expense")
        print(f"共 {len(exp_cats)} 个一级支出分类:")
        for cat in exp_cats[:5]:  # 只打印前 5 个
            subs = cat.get("sub_categories", [])
            print(f"  📂 {cat['name']} ({len(subs)} 个子分类)")
            for sub in subs[:3]:
                print(f"     - {sub['name']}")
        
        # 收入分类
        inc_cats = await client.get_categories(book_id, "Income")
        print(f"\n共 {len(inc_cats)} 个一级收入分类:")
        for cat in inc_cats:
            print(f"  📂 {cat['name']}")
        
        # --- 5. 当月汇总（核心统计接口）---
        current_month = datetime.now().strftime("%Y%m")
        print("\n" + "=" * 70)
        print(f"📌 5. 当月汇总统计 {current_month} (POST /v2/statistics/rollup-groups)")
        print("=" * 70)
        
        # 支出汇总
        exp_summary = await client.get_rollup_summary(
            book_id,
            group_key="TIME_MONTH",
            group_id=current_month,
            category_type="Expense",
        )
        print("【支出维度】总览:")
        for m in exp_summary.get("metric_data", []):
            print(f"  {m['label']}: {m['value']}")
        
        print("\n  分类 TOP 5:")
        for item in exp_summary.get("data", [])[:5]:
            name = item.get("group_info", {}).get("group_name", "?")
            amount = next(
                (m["value"] for m in item.get("metric_data", []) if m["key"] == "EXPENSE"),
                "0"
            )
            print(f"    - {name}: ¥{amount}")
        
        # 收入汇总
        inc_summary = await client.get_rollup_summary(
            book_id,
            group_key="TIME_MONTH",
            group_id=current_month,
            category_type="Income",
        )
        print("\n【收入维度】总览:")
        for m in inc_summary.get("metric_data", []):
            print(f"  {m['label']}: {m['value']}")
        
        # --- 6. 当月明细（自动翻页）---
        print("\n" + "=" * 70)
        print(f"📌 6. 当月交易明细 {current_month} (POST /v2/statistics/transactions)")
        print("=" * 70)
        txns = await client.get_all_transactions(book_id, current_month)
        print(f"共拉到 {len(txns)} 条交易")
        
        if txns:
            print("\n前 3 条示例:")
            for t in txns[:3]:
                dt = datetime.fromtimestamp(int(t["transaction_time"]) / 1000)
                print(f"  [{dt:%Y-%m-%d %H:%M}] "
                      f"{t.get('business_type'):10} "
                      f"¥{t.get('amount'):>10} | "
                      f"{t.get('category', {}).get('name', '?')} | "
                      f"{t.get('account', {}).get('name', '?')} | "
                      f"{t.get('remark', '')}")
        
        # --- 7. 多维度统计演示 ---
        print("\n" + "=" * 70)
        print("📌 7. 多维度统计示例")
        print("=" * 70)
        
        # 今日
        today = datetime.now().strftime("%Y%m%d")
        today_summary = await client.get_rollup_summary(
            book_id,
            group_key="TIME_DAY",
            group_id=today,
            category_type="Expense",
        )
        today_expense = next(
            (m["value"] for m in today_summary.get("metric_data", []) if m["key"] == "EXPENSE"),
            "0"
        )
        print(f"  今日支出 ({today}): ¥{today_expense}")
        
        # 按账户分组
        by_account = await client.get_rollup_summary(
            book_id,
            group_key="TIME_MONTH",
            group_id=current_month,
            category_type="Expense",
            group_by="ACCOUNT",
        )
        print(f"\n  本月按账户分组的支出（前 3）:")
        for item in by_account.get("data", [])[:3]:
            name = item.get("group_info", {}).get("group_name", "?")
            amount = next(
                (m["value"] for m in item.get("metric_data", []) if m["key"] == "EXPENSE"),
                "0"
            )
            print(f"    - {name}: ¥{amount}")
        
        # 按成员分组
        by_member = await client.get_rollup_summary(
            book_id,
            group_key="TIME_MONTH",
            group_id=current_month,
            category_type="Expense",
            group_by="MEMBER",
        )
        print(f"\n  本月按成员分组的支出:")
        for item in by_member.get("data", []):
            name = item.get("group_info", {}).get("group_name", "?")
            amount = next(
                (m["value"] for m in item.get("metric_data", []) if m["key"] == "EXPENSE"),
                "0"
            )
            print(f"    - {name}: ¥{amount}")
        
        print("\n" + "=" * 70)
        print("✅ 全部接口演示完毕")
        print("=" * 70)


if __name__ == "__main__":
    if PHONE == "你的手机号" or PASSWORD == "你的飞蛋密码明文":
        print("❌ 请先修改脚本顶部的 PHONE 和 PASSWORD")
    else:
        await main()    # ← Jupyter 直接 await 即可
