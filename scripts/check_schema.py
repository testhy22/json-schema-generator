#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JSON Schema 输出自检门禁（纯标准库，无第三方依赖）。

用法:
    python check_schema.py <schema.json> [example.json] [--json]
    python check_schema.py --selftest [--json]

两道闸门，缺一不可:
    1. 结构闸门 lint : Schema 是否符合产出规范（2020-12 关键字段齐全、内部自洽、
                       $ref 可解析、字段名 camelCase）
    2. 数据闸门 check: 示例数据能否真的通过该 Schema（常用关键字子集）

退出码契约:
    0 = 全部通过
    1 = 存在 ERROR（校验失败）
    2 = 参数或 IO 错误（输入无法读取）

--json 输出契约（供 CI / Agent 稳定解析）:
    {
      "status": "pass" | "fail" | "error",
      "exitCode": 0 | 1 | 2,
      "failures": [{"path": "...", "rule": "...", "message": "..."}],
      "warnings": [{"path": "...", "rule": "...", "message": "..."}],
      "summary": {"errors": 0, "warnings": 0, "checkedExample": true}
    }

边界约定:
    - 跨文件 $ref 一律报 ref-unsupported，不静默跳过
    - 循环 $ref（同一 Schema 在不消耗数据的情况下回到同一路径）报 ref-circular
    - 字段命名闸门只作用于 properties 的键；$defs / patternProperties 的键豁免
"""

import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"

# 字段名必须是 camelCase：小写字母开头，可由小写/大写/数字组成
FIELD_NAME_RE = re.compile(r"^[a-z][a-zA-Z0-9]*$")

LEGACY_KEYWORDS = {
    "definitions": "$defs",
    "dependencies": "dependentRequired / dependentSchemas",
}

FORMAT_PATTERNS = {
    "email": r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$",
    "uri": r"^[A-Za-z][A-Za-z0-9+.\-]*:\S+$",
    "ipv4": r"^(\d{1,3}\.){3}\d{1,3}$",
    "uuid": r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
}

TYPE_CHECK = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "null": lambda v: v is None,
}


@dataclass(frozen=True)
class Finding:
    """一条核查结果。字段一律具名访问 —— 禁止用位置下标，见下方实现约束。"""

    path: str
    rule: str
    severity: str      # "error" | "warn"
    message: str


class Report:
    """收集核查结果。rule 取自固定枚举，便于按规则聚合统计。

    实现约束（踩过坑，固化成契约）：
      1. 结果条目必须是带名字段（dataclass），不允许 tuple / 列表 + 下标访问；
         曾因列表推导里复用 `_` 导致 severity 判定实际比较的是 message。
      2. severity 判断只在具名属性上做（f.severity == "error"），
         不在推导里引用循环变量之外的临时名。
    """

    def __init__(self):
        self.findings = []

    def err(self, path, rule, msg):
        self.findings.append(Finding(path=path, rule=rule,
                                     severity="error", message=msg))

    def warn(self, path, rule, msg):
        self.findings.append(Finding(path=path, rule=rule,
                                     severity="warn", message=msg))

    @property
    def errors(self):
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self):
        return [f for f in self.findings if f.severity == "warn"]

    def payload(self, exit_code, extra=None):
        def pack(severity):
            seen, out = set(), []
            for f in self.findings:
                if f.severity != severity:
                    continue
                key = (f.path, f.rule, f.message)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"path": f.path, "rule": f.rule, "message": f.message})
            return out

        failures = pack("error")
        warnings = pack("warn")
        status = "error" if exit_code == 2 else ("fail" if failures else "pass")
        body = {
            "status": status,
            "exitCode": exit_code,
            "failures": failures,
            "warnings": warnings,
            "summary": {
                "errors": len(failures),
                "warnings": len(warnings),
                "checkedExample": BOOL_HINT["example"],
            },
        }
        if extra:
            body.update(extra)
        return body

    def dump(self):
        for f in self.findings:
            tag = "ERROR" if f.severity == "error" else "WARN "
            print("%s  [%-26s] %-38s %s" % (tag, f.rule, f.path, f.message))
        errs, warns = len(self.errors), len(self.warnings)
        if errs:
            print("\n结果: FAIL —— %d 个错误, %d 个提醒" % (errs, warns))
            return False
        print("\n结果: PASS —— 0 个错误, %d 个提醒" % warns)
        return True


BOOL_HINT = {"example": False}


def resolve_ref(ref, root):
    """仅支持文档内 $ref: '#/$defs/name' 与 '#'；其余一律返回 None（外部引用）。"""
    if ref == "#":
        return root
    if not ref.startswith("#/"):
        return None
    node = root
    for token in ref[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        else:
            return None
    return node


def lint(schema, root, path, rep, is_root=False):
    """结构闸门：只判产出规范，不看数据。"""
    if not isinstance(schema, dict):
        rep.err(path, "schema-shape", "Schema 节点必须是对象，实际是 %s"
                % type(schema).__name__)
        return

    if is_root:
        if schema.get("$schema") != DRAFT_2020_12:
            rep.err(path, "schema-version", "$schema 必须是 %s" % DRAFT_2020_12)
        if "$id" not in schema:
            rep.warn(path, "root-metadata", "缺少 $id（建议给出可读的稳定标识）")
        if not schema.get("title"):
            rep.warn(path, "root-metadata", "缺少 title")
        if not schema.get("description"):
            rep.warn(path, "root-metadata", "缺少顶层 description")
    elif "$id" in schema:
        rep.warn(path, "no-sub-id",
                 "子 Schema 不应声明 $id，否则会抬高 $ref 解析复杂度")

    for legacy, replacement in LEGACY_KEYWORDS.items():
        if legacy in schema:
            rep.err(path, "legacy-keyword",
                    "使用了 draft-07 关键字 '%s'，2020-12 应改用 %s"
                    % (legacy, replacement))

    node_type = schema.get("type")

    if node_type == "object" or "properties" in schema:
        props = schema.get("properties", {})
        if not isinstance(props, dict):
            rep.err(path, "schema-shape", "properties 必须是对象")
            props = {}
        if node_type == "object" and "additionalProperties" not in schema:
            rep.warn(path, "object-additional-properties",
                     "对象未声明 additionalProperties（严格模式应显式写 false）")
        required = schema.get("required", [])
        if not isinstance(required, list):
            rep.err(path, "schema-shape", "required 必须是数组")
            required = []
        for name in required:
            if name not in props:
                rep.err(path, "required-unknown-field",
                        "required 里的 '%s' 不在 properties 中" % name)
        if not required and props:
            rep.warn(path, "required-empty",
                     "对象有字段但 required 为空（确认是否真的全部可选）")

        for name, sub in props.items():
            sub_path = "%s.properties.%s" % (path, name)
            if not FIELD_NAME_RE.match(name):
                rep.err(sub_path, "field-naming",
                        "字段名 '%s' 不符合 camelCase（小写字母开头，仅字母数字）" % name)
            if not isinstance(sub, dict):
                rep.err(sub_path, "schema-shape", "字段定义必须是对象")
                continue
            desc = sub.get("description")
            if not isinstance(desc, str) or not desc.strip():
                rep.err(sub_path, "field-description",
                        "字段缺少 description（本 Skill 硬规则）")
        for name, sub in props.items():
            lint(sub, root, "%s.properties.%s" % (path, name), rep)

    if node_type == "array":
        if "items" not in schema and "prefixItems" not in schema:
            rep.err(path, "array-items", "数组既无 items 也无 prefixItems，元素类型不受约束")
        if isinstance(schema.get("items"), list):
            rep.err(path, "items-array-form",
                    "2020-12 的 items 不能是数组（元组请用 prefixItems）")

    for lo_key, hi_key in (("minLength", "maxLength"), ("minItems", "maxItems"),
                           ("minProperties", "maxProperties"), ("minimum", "maximum")):
        if lo_key in schema and hi_key in schema:
            lo, hi = schema[lo_key], schema[hi_key]
            if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo > hi:
                rep.err(path, "range-inconsistent",
                        "%s(%s) 大于 %s(%s)" % (lo_key, lo, hi_key, hi))

    for excl in ("exclusiveMinimum", "exclusiveMaximum"):
        if isinstance(schema.get(excl), bool):
            rep.err(path, "exclusive-boolean",
                    "%s 在 2020-12 中必须是数值，不能是布尔" % excl)

    if "multipleOf" in schema:
        mo = schema["multipleOf"]
        if not isinstance(mo, (int, float)) or mo <= 0:
            rep.err(path, "multiple-of", "multipleOf 必须是正数")

    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list) or not enum:
            rep.err(path, "enum-shape", "enum 必须是非空数组")
        elif len({json.dumps(v, sort_keys=True) for v in enum}) != len(enum):
            rep.err(path, "enum-shape", "enum 存在重复取值")

    if "pattern" in schema:
        try:
            re.compile(schema["pattern"])
        except re.error as exc:
            rep.err(path, "pattern-invalid", "pattern 非法正则: %s" % exc)

    if "format" in schema:
        fmt = schema["format"]
        if fmt not in FORMAT_PATTERNS and fmt not in ("date", "date-time"):
            rep.warn(path, "format-unknown",
                     "format '%s' 非内置常用格式，校验器可能忽略" % fmt)

    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#"):
            rep.err(path, "ref-unsupported",
                    "跨文件 $ref '%s' 不受支持，产出必须是自包含单文档" % ref)
        elif resolve_ref(ref, root) is None:
            rep.err(path, "ref-unresolved", "$ref '%s' 无法在文档内解析" % ref)

    for key in ("items", "additionalProperties", "contains", "propertyNames",
                "not", "if", "then", "else", "unevaluatedProperties"):
        if isinstance(schema.get(key), dict):
            lint(schema[key], root, "%s.%s" % (path, key), rep)
    for key in ("prefixItems", "allOf", "anyOf", "oneOf"):
        if isinstance(schema.get(key), list):
            for i, sub in enumerate(schema[key]):
                lint(sub, root, "%s.%s[%d]" % (path, key, i), rep)
    if isinstance(schema.get("$defs"), dict):
        for name, sub in schema["$defs"].items():
            lint(sub, root, "%s.$defs.%s" % (path, name), rep)
    if isinstance(schema.get("patternProperties"), dict):
        for name, sub in schema["patternProperties"].items():
            lint(sub, root, "%s.patternProperties.%s" % (path, name), rep)


def _type_ok(value, declared):
    names = declared if isinstance(declared, list) else [declared]
    return any(TYPE_CHECK.get(n, lambda v: True)(value) for n in names)


def _trial(value, schema, root, path, stack):
    probe = Report()
    validate(value, schema, root, path, probe, stack)
    return not probe.errors


def validate(value, schema, root, path, rep, stack=None):
    """数据闸门：示例数据能否通过 Schema（常用关键字子集）。"""
    if not isinstance(schema, dict):
        return

    stack = stack or []
    key = (id(schema), path)
    if key in stack:
        rep.err(path, "ref-circular",
                "循环 $ref：Schema 未消耗数据就回到同一路径，校验无法收敛")
        return
    stack = stack + [key]

    if "$ref" in schema:
        target = resolve_ref(schema["$ref"], root)
        if target is None:
            rep.err(path, "ref-unsupported",
                    "$ref '%s' 无法在文档内解析，数据校验中止" % schema["$ref"])
            return
        validate(value, target, root, path, rep, stack)
        if len(schema) == 1:
            return

    if "type" in schema and not _type_ok(value, schema["type"]):
        rep.err(path, "type-mismatch", "类型不符: 期望 %s，实际 %s"
                % (schema["type"], type(value).__name__))
        return

    if "const" in schema and value != schema["const"]:
        rep.err(path, "const-mismatch", "取值应恒等于 %r" % (schema["const"],))

    if isinstance(schema.get("enum"), list) and value not in schema["enum"]:
        rep.err(path, "enum-mismatch", "取值 %r 不在 enum %s 内"
                % (value, schema["enum"]))

    if isinstance(schema.get("allOf"), list):
        for sub in schema["allOf"]:
            validate(value, sub, root, path, rep, stack)
    if isinstance(schema.get("anyOf"), list):
        if not any(_trial(value, sub, root, path, stack) for sub in schema["anyOf"]):
            rep.err(path, "combinator", "anyOf 的所有分支均不匹配")
    if isinstance(schema.get("oneOf"), list):
        hits = sum(1 for sub in schema["oneOf"] if _trial(value, sub, root, path, stack))
        if hits != 1:
            rep.err(path, "combinator",
                    "oneOf 要求恰好命中 1 个分支，实际命中 %d 个" % hits)
    if isinstance(schema.get("not"), dict) and _trial(value, schema["not"], root, path, stack):
        rep.err(path, "combinator", "取值命中了 not 分支（应当被排除）")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            rep.err(path, "length", "长度 %d 小于 minLength %d"
                    % (len(value), schema["minLength"]))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            rep.err(path, "length", "长度 %d 大于 maxLength %d"
                    % (len(value), schema["maxLength"]))
        if "pattern" in schema:
            try:
                if not re.search(schema["pattern"], value):
                    rep.err(path, "pattern-mismatch",
                            "取值 %r 不匹配 pattern %s" % (value, schema["pattern"]))
            except re.error:
                pass
        fmt = schema.get("format")
        if fmt in FORMAT_PATTERNS:
            if not re.search(FORMAT_PATTERNS[fmt], value):
                rep.err(path, "format-mismatch",
                        "取值 %r 不符合 format '%s'" % (value, fmt))
        elif fmt == "date":
            try:
                date.fromisoformat(value)
            except ValueError:
                rep.err(path, "format-mismatch",
                        "取值 %r 不是合法 date (YYYY-MM-DD)" % value)
        elif fmt == "date-time":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                rep.err(path, "format-mismatch",
                        "取值 %r 不是合法 date-time (RFC 3339)" % value)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            rep.err(path, "numeric-range", "%s 小于 minimum %s"
                    % (value, schema["minimum"]))
        if "maximum" in schema and value > schema["maximum"]:
            rep.err(path, "numeric-range", "%s 大于 maximum %s"
                    % (value, schema["maximum"]))
        if isinstance(schema.get("exclusiveMinimum"), (int, float)) \
                and not isinstance(schema.get("exclusiveMinimum"), bool):
            if value <= schema["exclusiveMinimum"]:
                rep.err(path, "numeric-range", "%s 未大于 exclusiveMinimum %s"
                        % (value, schema["exclusiveMinimum"]))
        if "multipleOf" in schema and schema["multipleOf"] > 0:
            ratio = value / schema["multipleOf"]
            if abs(ratio - round(ratio)) > 1e-9:
                rep.err(path, "multiple-of", "%s 不是 multipleOf %s 的整数倍"
                        % (value, schema["multipleOf"]))

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            rep.err(path, "items-count", "元素数 %d 小于 minItems %d"
                    % (len(value), schema["minItems"]))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            rep.err(path, "items-count", "元素数 %d 大于 maxItems %d"
                    % (len(value), schema["maxItems"]))
        if schema.get("uniqueItems"):
            seen = [json.dumps(v, sort_keys=True, ensure_ascii=False) for v in value]
            if len(seen) != len(set(seen)):
                rep.err(path, "unique-items", "uniqueItems 为 true，但存在重复元素")
        prefixes = schema.get("prefixItems") or []
        for i, item in enumerate(value):
            if i < len(prefixes):
                validate(item, prefixes[i], root, "%s[%d]" % (path, i), rep, stack)
            elif isinstance(schema.get("items"), dict):
                validate(item, schema["items"], root, "%s[%d]" % (path, i), rep, stack)

    if isinstance(value, dict):
        props = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                rep.err(path, "required-missing", "缺少必填字段 '%s'" % name)
        for name, sub in props.items():
            if name in value:
                validate(value[name], sub, root, "%s.%s" % (path, name), rep, stack)
        extra = [k for k in value if k not in props]
        if extra and schema.get("additionalProperties") is False:
            rep.err(path, "additional-property",
                    "出现未声明字段 %s（additionalProperties: false）" % extra)
        elif extra and isinstance(schema.get("additionalProperties"), dict):
            for name in extra:
                validate(value[name], schema["additionalProperties"], root,
                         "%s.%s" % (path, name), rep, stack)


def check(schema, example=None):
    rep = Report()
    lint(schema, schema, "$", rep, is_root=True)
    if example is not None:
        validate(example, schema, schema, "$", rep)
    BOOL_HINT["example"] = example is not None
    return rep


def _case(label, schema, example, expect_rule=None):
    rep = check(schema, example)
    rules = {f.rule for f in rep.errors}
    if expect_rule is None:                       # 应当通过
        passed = not rules
    else:
        passed = expect_rule in rules
    return label, passed, sorted(rules)


def selftest():
    """证明门禁真的会失败：喂 10 个已知坏样本，必须全部被对应规则抓到。"""
    base = {
        "$schema": DRAFT_2020_12,
        "$id": "https://example.com/schemas/demo.json",
        "title": "自检样本",
        "description": "门禁自检用",
        "type": "object",
        "properties": {
            "userName": {"type": "string", "description": "名称"},
            "tags": {"type": "array", "description": "标签",
                     "items": {"type": "string", "description": "单个标签"}},
        },
        "required": ["userName"],
        "additionalProperties": False,
    }
    good = {"userName": "张三", "tags": ["a"]}

    def mutate(fn):
        dup = json.loads(json.dumps(base))
        fn(dup)
        return dup

    cases = [
        _case("基准样本必须通过", base, good, None),
        _case("字段缺 description",
              mutate(lambda s: s["properties"]["userName"].pop("description")),
              good, "field-description"),
        _case("数组缺 items",
              mutate(lambda s: s["properties"].__setitem__(
                  "tags", {"type": "array", "description": "标签"})),
              good, "array-items"),
        _case("字段名用 kebab-case",
              mutate(lambda s: s["properties"].__setitem__(
                  "user-name", {"type": "string", "description": "名称"})),
              good, "field-naming"),
        _case("字段名数字开头",
              mutate(lambda s: s["properties"].__setitem__(
                  "2faEnabled", {"type": "boolean", "description": "二次验证"})),
              good, "field-naming"),
        _case("示例含未声明字段", base, {"userName": "张三", "age": 3},
              "additional-property"),
        _case("示例类型不符", base, {"userName": 123}, "type-mismatch"),
        _case("required 指向不存在的字段",
              mutate(lambda s: s.__setitem__("required", ["nickname"])),
              good, "required-unknown-field"),
        _case("使用 draft-07 definitions",
              mutate(lambda s: s.__setitem__(
                  "definitions", {"x": {"type": "string", "description": "x"}})),
              good, "legacy-keyword"),
        _case("跨文件 $ref",
              mutate(lambda s: s["properties"]["userName"].__setitem__(
                  "$ref", "./common.json#/$defs/name")),
              good, "ref-unsupported"),
        _case("循环 $ref 不收敛",
              {"$schema": DRAFT_2020_12, "$id": "https://example.com/x.json",
               "title": "循环", "description": "自引用", "$ref": "#"},
              1, "ref-circular"),
    ]

    print("--- 门禁自检（%d 例） ---" % len(cases))
    ok = True
    for label, passed, rules in cases:
        ok = ok and passed
        print("%s  %-26s %s" % ("[PASS]" if passed else "[FAIL]", label,
                                "" if passed else "实际命中: %s" % rules))
    print("\n自检结论: %s" % ("门禁有效，坏样本全部被拦截" if ok
                              else "门禁失效，禁止交付"))
    return 0 if ok else 1


def run_cases(directory, json_mode=False):
    """用例驱动校验：读 cases/ 下的 *.json，逐个跑并比对期望。

    用例文件结构:
        {
          "description": "这条用例在验什么",
          "expect": "pass" | "fail",
          "expectRule": "field-naming",        // 可选，fail 用例建议必填
          "schema": { ... },
          "example": ...                        // 可选
        }
    expect 缺省时按所在目录名推断（pass/ 或 fail/）。
    """
    root = Path(directory)
    if not root.is_dir():
        print("用例目录不存在: %s" % directory, file=sys.stderr)
        return 2

    files = sorted(root.rglob("*.json"))
    if not files:
        print("用例目录内没有 .json 文件: %s" % directory, file=sys.stderr)
        return 2

    records = []
    for fp in files:
        rel = fp.relative_to(root).as_posix()
        try:
            case = json.loads(fp.read_text(encoding="utf-8"))
            schema = case["schema"]
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            records.append({"file": rel, "ok": False, "expect": "?",
                            "actual": "?",
                            "detail": "用例无法解析: %s" % exc, "rules": []})
            continue

        expect = case.get("expect")
        if not expect:
            expect = "pass" if "pass" in fp.parts else "fail"
        expect_rule = case.get("expectRule")

        rep = check(schema, case.get("example"))
        rules = sorted({f.rule for f in rep.errors})
        actual = "fail" if rules else "pass"
        ok = actual == expect and (not expect_rule or expect_rule in rules)

        detail = ""
        if not ok:
            detail = "期望 %s%s，实际 %s%s" % (
                expect,
                "（rule=%s）" % expect_rule if expect_rule else "",
                actual,
                "（%s）" % ",".join(rules) if rules else "")
        records.append({"file": rel, "ok": ok, "expect": expect,
                        "actual": actual, "detail": detail, "rules": rules})

    passed = sum(1 for r in records if r["ok"])
    failed = len(records) - passed
    code = 0 if failed == 0 else 1

    if json_mode:
        print(json.dumps({
            "status": "pass" if code == 0 else "fail",
            "exitCode": code,
            "cases": records,
            "summary": {"total": len(records), "passed": passed, "failed": failed},
        }, ensure_ascii=False, indent=2))
    else:
        print("--- 用例校验 %s（%d 个） ---" % (directory, len(records)))
        for r in records:
            print("%s  %-38s %s" % ("[PASS]" if r["ok"] else "[FAIL]",
                                    r["file"], r["detail"]))
        print("\n通过 %d / %d，失败 %d" % (passed, len(records), failed))
        print("结论: %s" % ("用例全绿" if code == 0 else "存在未达期望的用例"))
    return code


def main(argv):
    json_mode = "--json" in argv
    if "--selftest" in argv:
        return selftest()

    if "--cases" in argv:
        idx = argv.index("--cases")
        if idx + 1 >= len(argv):
            print("--cases 需要一个目录参数", file=sys.stderr)
            return 2
        return run_cases(argv[idx + 1], json_mode=json_mode)

    args = [a for a in argv[1:] if not a.startswith("--")]

    if len(args) not in (1, 2):
        print(__doc__)
        if json_mode:
            print(json.dumps(Report().payload(2), ensure_ascii=False))
        return 2

    try:
        with open(args[0], encoding="utf-8") as fh:
            schema = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print("无法读取 Schema: %s" % exc, file=sys.stderr)
        if json_mode:
            print(json.dumps(Report().payload(2), ensure_ascii=False, indent=2))
        return 2

    example = None
    if len(args) == 2:
        try:
            with open(args[1], encoding="utf-8") as fh:
                example = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print("无法读取示例数据: %s" % exc, file=sys.stderr)
            if json_mode:
                print(json.dumps(Report().payload(2), ensure_ascii=False, indent=2))
            return 2

    rep = check(schema, example)
    code = 0 if not rep.errors else 1
    if json_mode:
        print(json.dumps(rep.payload(code), ensure_ascii=False, indent=2))
    else:
        print("--- 自检 %s ---" % args[0])
        rep.dump()
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
