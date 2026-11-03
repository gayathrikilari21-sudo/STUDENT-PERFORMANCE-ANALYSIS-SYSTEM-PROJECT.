"""
All calculations of the project (total, percentage, grade, result, rank,
attendance, alerts and class statistics).  Pure Python - no database code.
"""
import config

GRADE_SCALE = [(90, "O"), (80, "A+"), (70, "A"), (60, "B"), (50, "C"), (40, "D")]
GRADE_ORDER = ["O", "A+", "A", "B", "C", "D", "F"]


def grade_for(percentage):
    for limit, grade in GRADE_SCALE:
        if percentage >= limit:
            return grade
    return "F"


def _pct(part, whole):
    return round(part / whole * 100, 2) if whole else None


def analyse(students, subjects, marks, attendance):
    """Return every number the pages need, calculated from raw table rows."""
    sub_map = {s["subject_code"]: s for s in subjects}

    marks_by = {}
    for m in marks:
        marks_by.setdefault(m["roll_no"], {})[m["subject_code"]] = m
    att_by = {}
    for a in attendance:
        att_by.setdefault(a["roll_no"], {})[a["subject_code"]] = a

    result_rows = []
    for st in students:
        roll = st["roll_no"]

        # ---------- marks ----------
        subj_rows = []
        for code in sorted(marks_by.get(roll, {})):
            sub = sub_map.get(code)
            if not sub:
                continue
            m = marks_by[roll][code]
            max_total = sub["max_internal"] + sub["max_external"]
            total = m["internal"] + m["external"]
            pct = _pct(total, max_total)
            subj_rows.append({
                "subject_code": code,
                "subject_name": sub["subject_name"],
                "internal": m["internal"],
                "external": m["external"],
                "total": total,
                "max_total": max_total,
                "percentage": pct,
                "grade": grade_for(pct),
                "result": "Pass" if pct >= config.MIN_PERCENTAGE else "Fail",
            })
        total = sum(r["total"] for r in subj_rows)
        max_total = sum(r["max_total"] for r in subj_rows)
        percentage = _pct(total, max_total)
        failed_subjects = [r["subject_code"] for r in subj_rows if r["result"] == "Fail"]
        if not subj_rows:
            result, grade = "N/A", "-"
        else:
            result = "Fail" if failed_subjects else "Pass"
            grade = grade_for(percentage)

        # ---------- attendance ----------
        att_rows = []
        for code in sorted(att_by.get(roll, {})):
            a = att_by[roll][code]
            sub = sub_map.get(code)
            if not sub:
                continue
            att_rows.append({
                "subject_code": code,
                "subject_name": sub["subject_name"],
                "held": a["classes_held"],
                "attended": a["classes_attended"],
                "percentage": _pct(a["classes_attended"], a["classes_held"]),
            })
        held = sum(r["held"] for r in att_rows)
        attended = sum(r["attended"] for r in att_rows)
        att_pct = _pct(attended, held)

        # ---------- alerts ----------
        alerts = []
        if percentage is not None and percentage < config.MIN_PERCENTAGE:
            alerts.append("Overall marks below %d%% (%.1f%%)" % (config.MIN_PERCENTAGE, percentage))
        if failed_subjects:
            alerts.append("Failed in: " + ", ".join(failed_subjects))
        if att_pct is not None and att_pct < config.MIN_ATTENDANCE:
            alerts.append("Attendance below %d%% (%.1f%%)" % (config.MIN_ATTENDANCE, att_pct))
        low_att = [r["subject_code"] for r in att_rows
                   if r["percentage"] is not None and r["percentage"] < config.MIN_ATTENDANCE]
        if low_att and not (att_pct is not None and att_pct < config.MIN_ATTENDANCE):
            alerts.append("Low attendance in: " + ", ".join(low_att))

        result_rows.append({
            "roll_no": roll, "name": st["name"], "email": st.get("email"),
            "section": st["section"], "subjects": subj_rows,
            "total": total, "max_total": max_total, "percentage": percentage,
            "grade": grade, "result": result,
            "attendance": att_rows, "att_held": held, "att_attended": attended,
            "att_pct": att_pct, "alerts": alerts, "rank": None,
        })

    # ---------- rank (ties share the same rank) ----------
    ranked = sorted([r for r in result_rows if r["percentage"] is not None],
                    key=lambda r: -r["percentage"])
    prev_pct, prev_rank = None, 0
    for i, r in enumerate(ranked, start=1):
        if r["percentage"] != prev_pct:
            prev_rank = i
            prev_pct = r["percentage"]
        r["rank"] = prev_rank

    # ---------- class statistics ----------
    subject_stats = []
    for sub in subjects:
        totals = []
        for roll in marks_by:
            m = marks_by[roll].get(sub["subject_code"])
            if m:
                totals.append(m["internal"] + m["external"])
        max_total = sub["max_internal"] + sub["max_external"]
        passed = sum(1 for t in totals if _pct(t, max_total) >= config.MIN_PERCENTAGE)
        subject_stats.append({
            "subject_code": sub["subject_code"],
            "subject_name": sub["subject_name"],
            "entered": len(totals),
            "average": round(sum(totals) / len(totals), 2) if totals else 0,
            "average_pct": _pct(sum(totals) / len(totals), max_total) if totals else 0,
            "highest": max(totals) if totals else 0,
            "lowest": min(totals) if totals else 0,
            "passed": passed,
            "failed": len(totals) - passed,
        })

    evaluated = [r for r in result_rows if r["result"] in ("Pass", "Fail")]
    passed = sum(1 for r in evaluated if r["result"] == "Pass")
    grade_dist = {g: 0 for g in GRADE_ORDER}
    for r in evaluated:
        grade_dist[r["grade"]] += 1

    entered_stats = [x for x in subject_stats if x["entered"]]
    hardest = min(entered_stats, key=lambda x: x["average_pct"]) if entered_stats else None
    easiest = max(entered_stats, key=lambda x: x["average_pct"]) if entered_stats else None
    scatter = [{"name": r["name"], "roll": r["roll_no"], "x": r["att_pct"], "y": r["percentage"]}
               for r in result_rows if r["att_pct"] is not None and r["percentage"] is not None]

    return {
        "hardest": hardest, "easiest": easiest, "scatter": scatter,
        "students": result_rows,
        "subjects": subjects,
        "subject_stats": subject_stats,
        "grade_dist": grade_dist,
        "grade_labels": GRADE_ORDER,
        "grade_counts": [grade_dist[g] for g in GRADE_ORDER],
        "evaluated": len(evaluated),
        "passed": passed,
        "failed": len(evaluated) - passed,
        "pass_percentage": _pct(passed, len(evaluated)) or 0,
        "class_average": round(sum(r["percentage"] for r in evaluated) / len(evaluated), 2)
                         if evaluated else 0,
        "toppers": ranked[:3],
        "alerts": [r for r in result_rows if r["alerts"]],
    }


def student_insights(me, a):
    """Plain, rule-based tips for one student (no machine learning)."""
    tips = []
    if me["percentage"] is not None:
        tips.append({"type": "info", "icon": "🎯",
                     "text": "Overall %.1f%% - grade %s - rank %s of %d."
                             % (me["percentage"], me["grade"], me["rank"], a["evaluated"])})
        diff = round(me["percentage"] - a["class_average"], 1)
        if diff >= 0:
            tips.append({"type": "good", "icon": "📈",
                         "text": "You are %.1f points above the class average (%.1f%%)." % (diff, a["class_average"])})
        else:
            tips.append({"type": "warn", "icon": "📉",
                         "text": "You are %.1f points below the class average (%.1f%%)." % (-diff, a["class_average"])})
        subs = me["subjects"]
        best = max(subs, key=lambda x: x["percentage"])
        worst = min(subs, key=lambda x: x["percentage"])
        tips.append({"type": "good", "icon": "💪",
                     "text": "Strongest subject: %s (%.1f%%)." % (best["subject_name"], best["percentage"])})
        if worst["percentage"] < config.MIN_PERCENTAGE:
            tips.append({"type": "bad", "icon": "🚨",
                         "text": "%s is below the pass mark (%.1f%%). Revise it first." % (worst["subject_name"], worst["percentage"])})
        elif worst is not best:
            tips.append({"type": "warn", "icon": "🔎",
                         "text": "Weakest subject: %s (%.1f%%). A little extra practice here lifts your total most."
                                 % (worst["subject_name"], worst["percentage"])})
        for limit, grade in reversed(GRADE_SCALE):
            if limit > me["percentage"]:
                need = int(-(-limit * me["max_total"] // 100)) - me["total"]
                tips.append({"type": "info", "icon": "🏅",
                             "text": "You need %d more marks in total to reach grade %s." % (max(need, 1), grade)})
                break
    if me["att_pct"] is not None:
        limit = config.MIN_ATTENDANCE / 100.0
        held, att = me["att_held"], me["att_attended"]
        if me["att_pct"] < config.MIN_ATTENDANCE:
            need = int(-(-(limit * held - att) // (1 - limit)))
            tips.append({"type": "bad", "icon": "⏰",
                         "text": "Attendance is %.1f%%. Attend the next %d classes without a break to reach %d%%."
                                 % (me["att_pct"], need, config.MIN_ATTENDANCE)})
        else:
            can_miss = int(att / limit - held)
            tips.append({"type": "good", "icon": "✅",
                         "text": "Attendance %.1f%% is good. You can miss at most %d more classes and stay above %d%%."
                                 % (me["att_pct"], max(can_miss, 0), config.MIN_ATTENDANCE)})
    if not tips:
        tips.append({"type": "info", "icon": "ℹ", "text": "Marks and attendance are not entered yet."})
    return tips
