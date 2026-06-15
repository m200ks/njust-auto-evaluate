"""
教务系统自动评教脚本

用法: python auto_evaluate.py

流程:
  1. 输入账号密码 → 自动识别验证码登录
  2. 获取所有评价批次和分类
  3. 遍历每个分类 → 每门未评课程
  4. 获取评价表单 → 自动打分 → 保存 (issubmit=0) → 回查验证
  5. 所有课程保存完毕后 → 统一提交 (issubmit=1) → 回查验证
"""
import random
import time

# 纯本地导入，不依赖外部目录
from captcha import recognize
from fetcher import PJFetcher


def log(msg: str):
    print(f"  {msg}", flush=True)


def section(title: str):
    print(f"\n{'=' * 55}")
    print(f"  {title}")
    print(f"{'=' * 55}")


def check_result(result: dict) -> tuple[bool, str]:
    """服务器 alert 为准"""
    alert = result.get("alert_msg", "")

    if "成功" in alert:
        return True, alert
    if "失败" in alert or "错误" in alert:
        return False, alert

    return False, f"未知: {alert[:80]}"


def summary(saved: int, submitted: int):
    section("总结")
    log(f"保存成功: {saved} 门")
    if submitted:
        log(f"提交成功: {submitted} 门")
    log("")


def main():
    print("=" * 55)
    print("  教务系统自动评教")
    print("  南京理工大学 - 强智科技教务系统")
    print("=" * 55)

    # ==================== 模式选择 ====================
    print("\n  模式选择:")
    print("    [1] 一键评教（保存 + ≥90分自动提交）")
    print("    [2] 仅保存不提交")
    print("    [3] 强制覆盖重做（含已提交课程）")
    mode_choice = input("  请输入 [1/2/3]（默认1）: ").strip() or "1"
    save_only = (mode_choice == "2")
    force = (mode_choice == "3")
    if save_only:
        print("  >> 模式: 仅保存不提交")
    elif force:
        print("  >> 模式: 强制覆盖重做")
    else:
        print("  >> 模式: 一键评教")

    # ==================== 登录 ====================
    username = input("\n账号: ").strip()
    password = input("密码: ").strip()
    if not username or not password:
        print("[ERROR] 账号密码不能为空")
        return

    fetcher = PJFetcher()
    print()

    for attempt in range(3):
        try:
            img_bytes = fetcher.get_captcha()
            code = recognize(img_bytes)
            log(f"验证码识别: {code}")
        except Exception as e:
            log(f"验证码获取/识别失败: {e}")
            continue

        result = fetcher.login(username, password, code)
        if result["success"]:
            log(f"✅ {result['msg']}")
            break
        if "验证码" in result.get("msg", "") or "码" in result.get("msg", ""):
            log(f"⏳ 第{attempt+1}次: {result['msg']}，重试...")
            continue
        log(f"❌ {result['msg']}")
        return
    else:
        log("❌ 登录失败，已达最大重试次数")
        return

    # ==================== 获取批次 ====================
    section("获取评价批次")
    batches = fetcher.get_batches()
    if not batches:
        log("❌ 未找到可评价的批次，可能不在评教时间段内")
        return

    # 按分类名分组展示
    log(f"找到 {len(batches)} 个评价分类:")
    for i, b in enumerate(batches):
        status = "已完成" if b.get("is_done") == "是" else "待评价"
        log(f"  [{i+1}] {b['category_name']:10s} | {b['batch_name']} | {status}")
        log(f"       pj0502id={b['pj0502id']}  pj01id={b['pj01id']}")

    # ==================== 遍历 - 第一步：全部保存 ====================
    section("第一步：保存所有课程评价")

    all_saved_courses = []  # (batch, course, form)

    for batch in batches:
        pj0502id = batch["pj0502id"]
        pj01id = batch["pj01id"]
        xnxq01id = batch["xnxq01id"]
        cat_name = batch["category_name"]

        log(f"\n▶ {cat_name} (pj01id={pj01id[:12]}...)")

        courses = fetcher.get_courses(pj0502id, xnxq01id, pj01id, force=force)
        log(f"  共 {len(courses)} 门课程")

        if force:
            pending = courses
        else:
            pending = [c for c in courses
                       if c["is_submitted"] != "是"
                       and (c["is_evaluated"] != "是" or c["total_score"] == "0")]
        skip = sum(1 for c in courses if c["is_submitted"] == "是")

        log(f"  已提交: {skip} 门, 待处理: {len(pending)} 门")

        for course in pending:
            log(f"\n  📝 {course['course_name']} - {course['teacher']}")

            # 获取评价表单（QFNU 方式：Form1 → indicator rows）
            try:
                form = fetcher.get_form(course)
            except Exception as e:
                log(f"  ❌ 获取表单失败: {e}")
                continue

            indicators = form.get("indicators", [])
            if not indicators:
                log(f"  ⚠️  未解析到评价指标，跳过")
                continue

            total_grades = sum(len(ind.get("grades", [])) for ind in indicators)
            log(f"     指标数: {len(indicators)}, 评分项: {total_grades}")

            # 保存
            try:
                result = fetcher.save_evaluation(form, course, issubmit=0)
            except Exception as e:
                log(f"  ❌ 保存请求异常: {e}")
                continue

            ok, detail = check_result(result)
            if ok:
                log(f"  ✅ 保存成功 ({detail})")
                all_saved_courses.append((batch, course, form))
            else:
                log(f"  ❌ 保存失败: {detail}")

            time.sleep(0.5 + random.random() * 0.5)

    if not all_saved_courses:
        log("  （没有需要新保存的课程，直接进入提交检查）")

    # ==================== 第二步：检查分数并自动提交 ====================
    section("第二步：检查分数 & 自动提交（≥90分）")

    submit_candidates = []   # (batch, course, form, score)
    already_done = 0

    for batch in batches:
        pj0502id = batch["pj0502id"]
        pj01id = batch["pj01id"]
        xnxq01id = batch["xnxq01id"]
        cat_name = batch["category_name"]

        courses = fetcher.get_courses(pj0502id, xnxq01id, pj01id, force=force)

        for c in courses:
            score_str = c["total_score"]
            try:
                score = float(score_str)
            except ValueError:
                score = 0

            if not force and c["is_submitted"] == "是":
                already_done += 1
            elif c["is_evaluated"] == "是" and score > 0:
                status = "≥90 ✅" if score >= 90 else f"<90 ⏭️"
                log(f"  [{status}] {c['course_name']:<20s} {c['teacher']:<8s} {score:5.1f}分  {cat_name}")
                if score >= 90:
                    submit_candidates.append((batch, c, score))

    if already_done > 0:
        log(f"\n  已提交: {already_done} 门（跳过）")

    if save_only:
        log("\n  >> 仅保存模式，到此为止。请手动检查分数后提交。")
        summary(len(all_saved_courses), 0)
        return

    if not submit_candidates:
        log("\n  没有需要提交的课程（全部已提交或分数不足90）")
        summary(len(all_saved_courses), 0)
        return

    log(f"\n  待提交（≥90分）: {len(submit_candidates)} 门")
    log("")

    submit_ok = 0
    submit_fail = 0

    for batch, course, score in submit_candidates:
        log(f"  📤 {course['course_name']} - {course['teacher']} ({score}分)")

        # 查找已有 form 或重新获取（必须匹配 jg0101id，区分同课不同老师）
        saved_form = None
        for _, bc, bf in all_saved_courses:
            if (bc["jx02id"] == course["jx02id"]
                    and bc["pj01id"] == course["pj01id"]
                    and bc["jg0101id"] == course["jg0101id"]):
                saved_form = bf
                break

        if not saved_form:
            try:
                saved_form = fetcher.get_form(course)
            except Exception as e:
                log(f"    ❌ 获取表单失败: {e}")
                submit_fail += 1
                continue

        try:
            result = fetcher.save_evaluation(saved_form, course, issubmit=1)
        except Exception as e:
            log(f"    ❌ 请求异常: {e}")
            submit_fail += 1
            continue

        ok, detail = check_result(result)
        if ok:
            log(f"    ✅ 提交成功 ({detail})")
            submit_ok += 1
        else:
            log(f"    ❌ 提交失败: {detail}")
            submit_fail += 1

        time.sleep(0.5 + random.random() * 0.5)

    summary(len(all_saved_courses), submit_ok)


if __name__ == "__main__":
    main()
