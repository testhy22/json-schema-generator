# JSON Schema 生成器 · CodeBuddy Skill

用自然语言描述数据结构，产出**能真正拦住脏数据**的 JSON Schema（Draft 2020-12）、可通过校验的示例数据，以及字段级校验说明表。

配套一个零依赖自检门禁，可在 CI 或 Agent 流程里机械判定产出是否合规。

## 这个 Skill 解决什么

大多数人用 AI 生成 Schema 会得到「长得像 Schema 的 JSON」：字段全 `string`、没 `required`、没 `description`、嵌套全靠猜。这份 Skill 把「写 Schema」变成一条有门禁的流水线：

- **严格优先** —— 对象默认 `additionalProperties: false`，脏字段不会静默入库
- **自包含** —— 单文件交付，跨文件 `$ref` 直接报错，不给你一个别人拿到就崩的产物
- **宁欠约束，不过约束** —— 描述没说长度就不写 `maxLength`，不编造会误杀合法数据的边界

## 安装

```bash
git clone <repo-url> json-schema-generator
```

放到用户的技能目录即可生效：

```bash
# 直接复制
cp -r json-schema-generator ~/.workbuddy/skills/

# 或者做目录联接，改了立刻生效（Windows）
mklink /J "%USERPROFILE%\.workbuddy\skills\json-schema-generator" "<repo-path>\json-schema-generator"
```

项目级安装则放到 `<project>/.workbuddy/skills/`。

## 用法

直接描述结构，Skill 会输出三段内容：Schema、示例数据、校验说明。

> 用户注册表单：用户名（必填，2-20 字符）、邮箱（必填）、密码（必填，至少 8 位且含字母与数字）、性别（男/女/保密，默认保密）、兴趣标签（可选，最多 10 个且唯一）

支持输入形态：自然语言、字段清单、存量 JSON 样本反推。

## 自检门禁

```bash
# 双闸门：结构规范 + 示例数据
python scripts/check_schema.py schema.json example.json

# 机器可读（CI / Agent 用）
python scripts/check_schema.py schema.json example.json --json

# 用例驱动回归集
python scripts/check_schema.py --cases cases

# 证明门禁本身会失败：11 个内联坏样本必须全部被拦住
python scripts/check_schema.py --selftest
```

| 退出码 | 含义 |
|---|---|
| `0` | 通过 |
| `1` | 存在校验失败，`failures` 非空 |
| `2` | 参数或 IO 错误，输入无法读取 |

`--json` 输出结构固定，可直接喂给 CI：

```json
{
  "status": "pass",
  "exitCode": 0,
  "failures": [{ "path": "$.username", "rule": "length", "message": "长度 1 小于 minLength 2" }],
  "warnings": [],
  "summary": { "errors": 0, "warnings": 0, "checkedExample": true }
}
```

### 两道闸门

| 闸门 | 查什么 |
|---|---|
| 结构 | `$schema` 是否 2020-12、字段 `description` 覆盖率、数组是否缺 `items`、`required` 是否指向不存在的字段、区间是否自相矛盾、`pattern` 能否编译、`$ref` 能否解析、字段名是否 camelCase、是否残留 draft-07 关键字 |
| 数据 | 示例数据按 type / required / additionalProperties / enum / const / 长度 / 数值区间 / multipleOf / pattern / format / uniqueItems / oneOf / anyOf / allOf 逐项核对 |

### 假通过专项

`cases/fail/defs-hidden-invalid.json` 是顶层完全合法、示例也能通过数据闸门的样本，只有 `$defs` 内一个字段缺 `description`。若它返回 `pass`，说明校验没递归进 `$defs`——视为门禁缺陷。

## 目录结构

```text
json-schema-generator/
├── SKILL.md                    # 技能正文：工作流、约束、示例模板、边界处理
├── scripts/
│   └── check_schema.py         # 自检门禁（纯标准库，无第三方依赖）
└── cases/
    ├── pass/                   # 必须通过的样本
    └── fail/                   # 必须被判失败的样本（含假通过专项）
```

## 为什么门禁要「证明自己会失败」

`--selftest` 会喂 11 个已知坏样本，全部被拦住才算门禁有效。这条约束来自一次真实事故：自检代码在列表推导里复用了循环变量，导致 `severity == "error"` 实际比较的是错误消息，**11 个坏样本全部漏判**，而门禁仍显示全绿。

所以本仓库的规矩是：

- 失败条目用 `@dataclass(frozen=True) Finding`，禁止位置下标访问
- 用例的 `fail` 样本必须断言 `expectRule`，防止「因为别的原因失败」被当通过
- 改门禁规则必须在 `SKILL.md` 版本历史里登记，未登记视为规则漂移

## License

MIT
