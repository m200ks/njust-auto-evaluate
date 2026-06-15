"""
教务系统评教 - 数据抓取模块
自带登录、验证码、session 管理，不依赖外部模块
"""
import re
import random
import requests
from bs4 import BeautifulSoup

BASE_8080 = "http://202.119.81.112:8080"
BASE_9080 = "http://202.119.81.112:9080"


class PJFetcher:
    """教务系统评教 Fetcher —— 登录 + session + 评教方法"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/149.0.0.0 Safari/537.36 Edg/149.0.0.0"
            ),
        })
        self.logged_in = False
        self.username = None
        self.name = None

    # ==================== 验证码 ====================

    def get_captcha(self) -> bytes:
        resp = self.session.get(f"{BASE_8080}/verifycode.servlet", timeout=10)
        return resp.content

    # ==================== 登录 ====================

    def login(self, username: str, password: str, captcha_code: str) -> dict:
        self.username = username

        resp = self.session.post(
            f"{BASE_8080}/Logon.do?method=logon",
            data={
                "USERNAME": username,
                "PASSWORD": password,
                "useDogCode": "",
                "RANDOMCODE": captcha_code,
            },
            allow_redirects=False,
            timeout=15,
        )

        if resp.status_code == 302:
            location = resp.headers.get("location", "")
            if "LoginToXk" in location:
                resp2 = self.session.get(location, allow_redirects=True, timeout=15)
                if resp2.status_code == 200:
                    self.logged_in = True
                    self._extract_name(resp2.text)
                    return {"success": True, "msg": f"登录成功, 欢迎 {self.name or username}"}
                return {"success": False, "msg": f"二次跳转失败: {resp2.status_code}"}
            return {"success": False, "msg": f"登录跳转异常: {location[:80]}"}

        soup = BeautifulSoup(resp.text, "html.parser")
        error = soup.find("font", color="red")
        if error:
            return {"success": False, "msg": error.text.strip()}
        return {"success": False, "msg": f"登录失败: HTTP {resp.status_code}"}

    def _extract_name(self, html: str):
        import re as _re
        match = _re.search(r'divLoginName.*?>([^<]+)</div>', html)
        if match:
            self.name = match.group(1).strip()
        else:
            soup = BeautifulSoup(html, "html.parser")
            for div in soup.find_all("div"):
                if div.get("id", "").endswith("divLoginName"):
                    self.name = div.text.strip()
                    break

    def _get_page(self, path: str) -> str:
        resp = self.session.get(f"{BASE_9080}{path}", timeout=15)
        resp.encoding = "utf-8"
        return resp.text

    # ==================== 1. 获取评价批次/分类列表 ====================

    def get_batches(self) -> list[dict]:
        """
        GET xspj_find.do → 解析批次和分类列表
        返回: [{xnxq01id, pj0502id, pj01id, category_name, batch_name, start_date, end_date, is_done}]
        """
        html = self._get_page("/njlgdx/xspj/xspj_find.do")
        soup = BeautifulSoup(html, "html.parser")

        batches = []
        # 找主表格: 包含 "评价分类" 表头的那个
        table = None
        for t in soup.find_all("table"):
            headers = [th.get_text(strip=True) for th in t.find_all("th")]
            if "评价分类" in headers:
                table = t
                break

        if not table:
            return batches

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 8:
                continue

            texts = [c.get_text(strip=True) for c in cells]
            if texts[0] == "序号":
                continue  # 跳过表头

            # 解析操作列里的链接 (每个分类有多个链接: 理论课评教、理论课评课等)
            ops_cell = cells[-1]
            for link in ops_cell.find_all("a"):
                href = link.get("href", "")
                params = self._parse_query(href)

                pj0502id = params.get("pj0502id", "")
                xnxq01id = params.get("xnxq01id", texts[1])  # fallback 用表格的学年学期
                pj01id = params.get("pj01id", "")

                if not pj0502id or not pj01id:
                    continue

                batches.append({
                    "xnxq01id": xnxq01id,
                    "pj0502id": pj0502id,
                    "pj01id": pj01id,
                    "category_name": link.get_text(strip=True),  # "理论课评教"
                    "batch_name": texts[3],      # "2025-2026-2学期末评教"
                    "start_date": texts[4],
                    "end_date": texts[5],
                    "is_done": texts[6],          # "是" / "否"
                })

        return batches

    # ==================== 2. 获取课程列表 ====================

    def get_courses(self, pj0502id: str, xnxq01id: str, pj01id: str,
                   force: bool = False) -> list[dict]:
        """
        GET xspj_list.do → 解析课程列表
        返回: [{course_code, course_name, teacher, total_score, is_evaluated, is_submitted,
                jx02id, jx0404id, jg0101id, zpf, xsflid}]
        """
        url = f"/njlgdx/xspj/xspj_list.do?pj0502id={pj0502id}&xnxq01id={xnxq01id}&pj01id={pj01id}"
        html = self._get_page(url)
        soup = BeautifulSoup(html, "html.parser")

        courses = []
        # 找表格: 包含 "课程名称" 和 "授课教师" 表头的
        table = None
        for t in soup.find_all("table"):
            headers = [th.get_text(strip=True) for th in t.find_all("th")]
            if "课程名称" in headers and "授课教师" in headers:
                table = t
                break

        if not table:
            return courses

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 8:
                continue

            texts = [c.get_text(strip=True) for c in cells]
            if texts[0] == "序号":
                continue

            # 提取操作链接中的参数（一个单元格可能有多个链接，每个对应不同老师）
            ops_cell = cells[-1]
            links = ops_cell.find_all("a")
            if not links:
                continue

            for link in links:
                href = link.get("href", "")
                # href 格式: javascript:openWindow('/njlgdx/xspj/xspj_edit.do?...',1000,700)
                # 或带 VPN 包装的变体
                match = re.search(r"'([^']*xspj_edit\.do[^']*)'", href)
                if not match:
                    continue

                edit_url = match.group(1)
                params = self._parse_query(edit_url)

                # type=view 表示"查看"（已提交过的），force 模式下不跳过
                if not force and params.get("type") == "view":
                    continue

                courses.append({
                    "course_code": texts[1],
                    "course_name": texts[2],
                    "teacher": texts[3],
                    "total_score": texts[4],
                    "is_evaluated": texts[5],
                    "is_submitted": texts[6],
                    "jx02id": params.get("jx02id", ""),
                    "jx0404id": params.get("jx0404id", ""),
                    "jg0101id": params.get("jg0101id", ""),
                    "zpf": params.get("zpf", "0"),
                    "xsflid": params.get("xsflid", ""),
                    "xnxq01id": xnxq01id,
                    "pj0502id": pj0502id,
                    "pj01id": pj01id,
                })

        return courses

    # ==================== 3. 获取评价表单（参考 QFNU 强智解析方式） ====================

    def get_form(self, course: dict) -> dict:
        """
        GET xspj_edit.do → 按 QFNU 方式解析 Form1 表单
        返回: {
            static_params: {name: value},   # 隐藏字段
            indicators: [{pj06xh, grades: [{grade_id, score, grade_name}]}],
            course_info: {...},
        }
        """
        edit_url = (
            f"/njlgdx/xspj/xspj_edit.do"
            f"?xnxq01id={course['xnxq01id']}"
            f"&pj01id={course['pj01id']}"
            f"&pj0502id={course['pj0502id']}"
            f"&jx02id={course['jx02id']}"
            f"&jx0404id={course['jx0404id']}"
            f"&xsflid={course['xsflid']}"
            f"&zpf={course['zpf']}"
            f"&jg0101id={course['jg0101id']}"
        )

        html = self._get_page(edit_url)
        soup = BeautifulSoup(html, "html.parser")

        # 1. 找 Form1
        form = soup.find("form", {"id": "Form1"})
        if not form:
            form = soup.find("form")
            if not form:
                return {"static_params": {}, "indicators": [], "course_info": course}

        # 2. 提取静态隐藏字段
        static_params: dict[str, str] = {}
        for inp in form.find_all("input", {"type": "hidden"}):
            name = inp.get("name", "")
            value = inp.get("value", "")
            if name and name != "pj06xh":
                static_params[name] = value

        # 3. 提取动态指标: tr:has(input[name="pj06xh"])
        indicators: list[dict] = []
        indicator_rows = form.select('tr:has(input[name="pj06xh"])')

        if not indicator_rows:
            # fallback: 直接从原始 HTML 用正则提取 pj06xh 和 pj0601fz
            return self._fallback_parse(html, static_params, course)

        for row in indicator_rows:
            ind_input = row.find("input", {"name": "pj06xh"})
            if not ind_input:
                continue
            indicator_id = ind_input.get("value", "")
            if not indicator_id:
                continue

            grades = []

            # 找指标选项单元格 td[name="zbtd"]
            options_cell = row.find("td", {"name": "zbtd"})
            if not options_cell:
                # fallback: 整行搜 radio
                options_cell = row

            for radio in options_cell.find_all("input", {"type": "radio"}):
                option_id = radio.get("value", "")
                radio_name = radio.get("name", "")

                # 取 radio 后面的文本节点（如 "优(10)" 或纯数字分值）
                text_node = radio.next_sibling
                grade_text = ""
                if text_node:
                    grade_text = str(text_node).strip()
                    # 从 "优(10)" 提取 "优", 或从纯数字提取自身
                    m = re.match(r'(\w+)\(', grade_text)
                    if m:
                        grade_text = m.group(1)

                # 取紧跟的 hidden input 作为分值
                score_input = radio.find_next_sibling("input", {"type": "hidden"})
                score = "0"
                if score_input:
                    score = score_input.get("value", "0")

                # 如果没有 hidden input，用 radio 的 value 作为分值（NJUST 情况）
                if score == "0" and radio.get("value"):
                    score = radio.get("value", "0")

                grades.append({
                    "grade_id": option_id,
                    "score": score,
                    "grade_name": grade_text,
                    "radio_name": radio_name,
                })

            if grades:
                indicators.append({
                    "pj06xh": indicator_id,
                    "grades": grades,
                })

        return {
            "static_params": static_params,
            "indicators": indicators,
            "course_info": course,
        }

    def _fallback_parse(self, html: str, static_params: dict, course: dict) -> dict:
        """正则兜底：当 BeautifulSoup 找不到 indicator rows 时使用"""
        indicators: list[dict] = []

        # 搜所有 pj06xh 的 hidden input
        xh_pattern = re.compile(r'name="pj06xh"\s+value="(\d+)"')
        found_xh = xh_pattern.findall(html)

        # 搜所有 pj0601fz 的 radio name 和 value
        radio_pattern = re.compile(
            r'pj0601fz_(\d+)_([A-F0-9]+).*?value="([^"]+)"'
        )

        # 按 pj06xh 分组 radio
        groups: dict[str, list[dict]] = {}
        for m in radio_pattern.finditer(html):
            pj06xh = m.group(1)
            sub_id = m.group(2)
            score = m.group(3)
            groups.setdefault(pj06xh, []).append({
                "grade_id": sub_id,
                "score": score,
                "grade_name": "",
                "radio_name": f"pj0601fz_{pj06xh}_{sub_id}",
            })

        if not groups:
            # 最后手段：只用捕获数据中的格式（12.5/10/7.5/5/2.5）
            return {"static_params": static_params, "indicators": [], "course_info": course}

        for pj06xh in sorted(groups.keys(), key=int):
            indicators.append({
                "pj06xh": pj06xh,
                "grades": groups[pj06xh],
            })

        return {
            "static_params": static_params,
            "indicators": indicators,
            "course_info": course,
        }

    # ==================== 4. 保存/提交评价（参考 QFNU payload 构建） ====================

    def save_evaluation(self, form: dict, course: dict,
                        issubmit: int = 0) -> dict:
        """
        POST xspj_save.do → 保存或提交
        用 alert('...') 判断成败（参考 QFNU）
        """
        payload = self._build_payload(form, issubmit)

        course_info = form.get("course_info", course)

        url = f"{BASE_9080}/njlgdx/xspj/xspj_save.do"
        referer = (
            f"{BASE_9080}/njlgdx/xspj/xspj_edit.do"
            f"?xnxq01id={course_info.get('xnxq01id', '')}"
            f"&pj01id={course_info.get('pj01id', '')}"
            f"&pj0502id={course_info.get('pj0502id', '')}"
            f"&jx02id={course_info.get('jx02id', '')}"
            f"&jx0404id={course_info.get('jx0404id', '')}"
            f"&xsflid={course_info.get('xsflid', '')}"
            f"&zpf={course_info.get('zpf', '0')}"
            f"&jg0101id={course_info.get('jg0101id', '')}"
        )

        resp = self.session.post(
            url,
            data=payload,
            headers={
                "Referer": referer,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=15,
        )

        resp.encoding = "utf-8"
        resp_text = resp.text

        # QFNU 方式: 正则提取 alert 内容
        alert_match = re.search(r"alert\('(.*?)'\)", resp_text)
        alert_msg = alert_match.group(1) if alert_match else resp_text[:200]

        # 回查验证
        status = self._check_course_status(course_info)

        return {
            "http_status": resp.status_code,
            "response_text": resp_text[:500],
            "alert_msg": alert_msg,
            "evaluated": status["evaluated"],
            "submitted": status["submitted"],
        }

    def _check_course_status(self, course: dict) -> dict:
        """GET xspj_list.do → 按 jx02id 找到课程 → 返回实际状态"""
        try:
            url = (
                f"/njlgdx/xspj/xspj_list.do"
                f"?pj0502id={course['pj0502id']}"
                f"&xnxq01id={course['xnxq01id']}"
                f"&pj01id={course['pj01id']}"
            )
            html = self._get_page(url)
            soup = BeautifulSoup(html, "html.parser")

            table = None
            for t in soup.find_all("table"):
                headers = [th.get_text(strip=True) for th in t.find_all("th")]
                if "课程名称" in headers and "授课教师" in headers:
                    table = t
                    break
            if not table:
                return {"evaluated": "?", "submitted": "?"}

            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 8:
                    continue
                code = cells[1].get_text(strip=True)
                if code == course.get("jx02id", ""):
                    texts = [c.get_text(strip=True) for c in cells]
                    return {
                        "evaluated": texts[5] if len(texts) > 5 else "?",
                        "submitted": texts[6] if len(texts) > 6 else "?",
                    }
            return {"evaluated": "?", "submitted": "?"}
        except Exception:
            return {"evaluated": "?", "submitted": "?"}

    def _build_payload(self, form: dict, issubmit: int) -> dict:
        """
        构造 POST payload（参考 QFNU 方式）
        - 静态字段直接 copy
        - pj06xh 传 list（requests 自动展开为多个同名参数）
        - 每个指标: 随机选一个等级打第二高分，其余最高分
        - issubmit 控制保存/提交
        """
        static_params = form.get("static_params", {})
        indicators = form.get("indicators", [])

        payload: dict[str, object] = dict(static_params)
        payload["issubmit"] = str(issubmit)

        if not indicators:
            return payload

        # 构建指标序号列表
        pj06xh_list: list[str] = []

        # 为每个指标决定选中哪个等级（第二个为"第二高分"）
        # 策略: 随机挑一个指标打第二高分（良），其余打最高分（优）
        second_best_idx = random.randrange(len(indicators))

        for i, ind in enumerate(indicators):
            pj06xh = ind["pj06xh"]
            pj06xh_list.append(pj06xh)
            grades = ind["grades"]

            if not grades:
                continue

            # 按分值从高到低排序
            try:
                grades_sorted = sorted(grades, key=lambda g: float(g["score"]), reverse=True)
            except (ValueError, KeyError):
                grades_sorted = grades

            # 决定选哪个等级
            if i == second_best_idx and len(grades_sorted) >= 2:
                selected = grades_sorted[1]  # 第二高分
            else:
                selected = grades_sorted[0]  # 最高分

            # pj0601id = 选中等级的 grade_id
            payload[f"pj0601id_{pj06xh}"] = selected.get("grade_id", "")

            # 所有等级的分数都要放进去
            for g in grades:
                grade_id = g.get("grade_id", "")
                score = g.get("score", "0")
                payload[f"pj0601fz_{pj06xh}_{grade_id}"] = score

        payload["pj06xh"] = pj06xh_list

        return payload

    # ==================== 工具方法 ====================

    @staticmethod
    def _parse_query(url: str) -> dict:
        """从 URL 中提取 query string 参数"""
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        # parse_qs 返回 {key: [value1, value2]}, 转成 {key: value}
        return {k: v[0] if v else "" for k, v in params.items()}
