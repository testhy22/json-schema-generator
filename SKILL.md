---
name: json-schema-generator
description: 把自然语言描述的数据结构编译为符合 JSON Schema Draft 2020-12 的 Schema、可通过校验的示例数据与字段校验说明表。当用户描述字段清单、表结构、API 请求或响应体、表单校验规则、配置文件结构，或直接要求"生成 JSON Schema / 数据模型 / 校验规则 / 定义接口字段"时使用。支持中英文混合输入、嵌套对象、对象数组与条件必填。
agent_created: true
version: 1.0.2
license: MIT
---

# JSON Schema 生成器

## 概述

本 Skill 把一段自由格式的数据结构描述，编译成**一组可直接落地的产物**：Draft 2020-12 的 JSON Schema、一份能真的通过该 Schema 的示例数据、一张人读的校验说明表。

它解决的不是「写一个长得像 Schema 的 JSON」，而是「写一个既能拦住脏数据、又不会误杀合法数据的 Schema」。

### 三条设计原则

以下三条会直接改变产出，遇到取舍时按此裁决，不要自行发挥。

| 原则 | 含义 | 反面案例 |
|------|------|----------|
| 严格优先 | 对象默认 `additionalProperties: false` | 省略该字段 ⇒ 多余字段静默通过，脏数据入库 |
| 自包含 | 单文件即可交付，跨实体复用才用 `$defs` + 文档内 `$ref` | 引用 `./common.json`，对方拿到文件就崩 |
| 宁欠约束，不过约束 | 信息缺失时省略约束，不编造边界 | 擅自给 `username` 加 `maxLength: 20`，误杀合法数据 |

第三条最容易被违反：编一个「看起来合理」的上限，比不写约束危险得多。**没有依据的数字一律不写。**

### 核心能力

| 能力 | 说明 |
|------|------|
| 描述解析 | 从中英文混合的非结构化文本中抽取字段名、类型、约束、层级归属 |
| 类型推断 | 按语义关键词映射到 `string` / `integer` / `number` / `boolean` / `array` / `object` / `null` |
| 格式识别 | 自动应用 `email`、`uri`、`date`、`date-time`、`ipv4`、`uuid` 等内置 format |
| 结构表达 | 多层嵌套对象、对象数组、元组（`prefixItems`）、字典（`additionalProperties` + 值类型） |
| 条件约束 | 条件必填（`dependentRequired`）、按取值分派（`oneOf` + `if/then`）、互斥字段 |
| 示例生成 | 产出语义真实、可通过自身 Schema 校验的实例，不用 `foo` / `test` 占位 |
| 校验说明 | 输出字段级说明表，含类型、必填性、约束、业务含义 |
| 自检门禁 | 用随附脚本机械核对「结构规范 + 示例真能通过」两件事 |

## 适用场景

| 场景 | 典型输入 | 产物用途 |
|------|----------|----------|
| API 契约 | "设计一个创建订单的请求体" | 后端入参校验、前端类型生成 |
| 表单校验 | "注册表单：邮箱必填、密码至少 8 位" | 前端校验规则、错误文案映射 |
| 配置定义 | "数据库连接配置，含主从节点" | 启动期配置校验、配置文档 |
| 数据交换 | "物流运单交换格式" | 上下游对接、Schema Registry |
| 数据管道 | "埋点事件：事件名、时间、用户、属性字典" | 落库前过滤、Iceberg / Parquet 表结构 |
| 存量反推 | 给一段真实 JSON 样本 | 反向建模，再收紧为严格 Schema |

### 不适用场景

命中以下情况应直接说明并转向，不要硬做。

| 情况 | 原因 | 建议去向 |
|------|------|----------|
| 需要表达跨字段算术关系（`total = sum(items)`） | JSON Schema 无算术能力 | 用业务层校验或 JSON Schema + 自定义关键字 |
| 需要生成完整 OpenAPI 文档 | Schema 只是其中一小块 | 先出 Schema，再套 OpenAPI 骨架 |
| 需要数据库 DDL | 类型体系不同（索引、外键、字符集） | 由 Schema 派生 DDL，另走建模流程 |
| 需要执行数据校验本身 | 本 Skill 只产出定义 | 交付后用 Ajv / python-jsonschema 跑真实数据 |

## 工作流定义

六步串行，任一步的门禁不过就停在原地修，不带着缺陷往下走。

| 步骤 | 名称 | 产出 | 通过条件 |
|------|------|------|----------|
| 0 | 需求分级 | 开工 / 带假设开工 / 先追问 的判定 | 判定明确，不空转 |
| 1 | 解析与建模 | 字段清单（中→英映射 + 层级） | 每个字段都有归属和英文名 |
| 2 | 类型与约束推断 | 字段级 type + 关键字 | 无「不确定类型」遗留 |
| 3 | 组装 Schema | 完整 Schema | 通过结构闸门 |
| 4 | 生成示例数据 | 一份实例 JSON | 通过数据闸门（真跑一次） |
| 5 | 输出说明表 | Markdown 表格 | 字段覆盖率 100% |

### 步骤 0 —— 需求分级

不要一上来就追问，也不要一上来就瞎猜。按输入完整度分三档：

| 输入形态 | 判定 | 动作 |
|----------|------|------|
| 字段名 + 类型/必填性基本齐全 | 直接开工 | 补齐推断细节，注明假设 |
| 只给实体名（如"生成一个用户 Schema"） | 带假设开工 | 先给一版覆盖常见字段的草案，**在草案下方单列「我假设了什么」**，请用户删改 |
| 描述自相矛盾（"必填，但可能不传"） | 先澄清 | 指出矛盾原句，给两种解法让用户选 |

**关键**：只有「矛盾」和「类型真的无法判断」两种情形值得中断。其余一律带假设推进 —— 用户改草案比回答问卷快得多。

### 步骤 1 —— 解析与建模

1. **定顶层形态**：单一对象、顶层数组、还是多个独立实体（多个实体 ⇒ 拆成多个 Schema 或用 `$defs`）。
2. **抽字段并定位层级**：把描述里的「客户信息（userId + 昵称）」展开成嵌套对象，而不是拍平成 `customerUserId`。
3. **捕获修饰词**：必填 / 可选 / 唯一 / 至少 N / 最多 N / 默认 X / 格式。
4. **标记歧义**：记下无法判断的项，进入步骤 0 的分级处理。

**中译英命名规则**（字段名一律 camelCase）：

| 中文 | 结果 | 规则 |
|------|------|------|
| 用户名 | `username` | 业界惯用词优先，不用 `userName` |
| 手机号 | `phoneNumber` | 复合词 camelCase |
| 创建时间 / 更新时间 | `createdAt` / `updatedAt` | 时间点以 `-At` 结尾 |
| 是否启用 | `isEnabled` | 布尔用 `is` / `has` / `can` 前缀 |
| 商品列表 | `items` | 数组用复数名词，不加 `List` 后缀 |
| 收货地址 | `shippingAddress` | 用行业术语，不用拼音 |
| 金额 | `amount` / `unitPrice` | 带单位含义的词不要省（`price` 易歧义） |

### 步骤 2 —— 类型与约束推断

按关键词查表，命中即用；表内没有的，按字段语义判断，仍无法判断才追问。

| 关键词 | 类型 | 附加约束 |
|--------|------|----------|
| 邮箱 / email | `string` | `format: "email"` |
| 链接 / URL / 地址（网页） | `string` | `format: "uri"` |
| 日期 | `string` | `format: "date"` |
| 时间 / 日期时间 | `string` | `format: "date-time"` |
| IP | `string` | `format: "ipv4"` |
| UUID / 唯一标识 | `string` | `format: "uuid"` |
| 年龄 | `integer` | `minimum: 0`、`maximum: 150`（语义明确才写） |
| 数量 / 件数 | `integer` | `minimum: 0` 或 `1`（视语义） |
| 价格 / 金额 | `number` | `minimum: 0`、`multipleOf: 0.01` |
| 比例 / 折扣率 | `number` | `minimum: 0`、`maximum: 1`（若描述为百分比则用 0-100） |
| 是否 / 启用 | `boolean` | 无 |
| 标签 / 列表 / 明细 | `array` | 必须给出 `items` |
| 地址 / 配置 / 信息（含子字段） | `object` | 递归处理，独立 `required` |
| 枚举（"男/女"） | `string` | `enum`，取值转小写下划线（`male` / `undisclosed`） |
| 字典 / 映射 / 扩展属性 | `object` | `additionalProperties: { 值类型 }` |

**约束映射**：

| 描述 | 关键字 |
|------|--------|
| 必填 | 加入**最近作用域**的 `required` |
| 可选 | 不加入 `required` |
| 至少 N 个字符 / 项 | `minLength` / `minItems` |
| 最多 N 个字符 / 项 | `maxLength` / `maxItems` |
| N 到 M 之间 | `minimum` + `maximum` |
| 唯一 | `uniqueItems: true`（数组）/ `enum` 去重（字符串） |
| 默认 X | `default: X` |
| 格式为 ...（自定义） | `pattern`，且必须可编译 |
| 仅当 A 存在时必填 | `dependentRequired: { "A": ["B"] }` |
| 仅当 A 为 X 时必填 | `if` / `then` |
| A 与 B 互斥 | `oneOf` + `not`，或拆两个分支对象 |

### 步骤 3 —— 组装 Schema

**骨架**：

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.com/schemas/entity-name.json",
  "title": "实体标题（中文可读）",
  "description": "一句话说明这个 Schema 约束的是什么数据",
  "type": "object",
  "properties": {},
  "required": [],
  "additionalProperties": false
}
```

**八条硬规则**：

1. `$schema` 固定为 `https://json-schema.org/draft/2020-12/schema`，不写 draft-07。
2. `$id` 用 `https://example.com/schemas/` + 实体名 kebab-case；它只是标识符，不会被联网解析。
3. **每个字段**必须有 `description`；枚举字段在 `description` 里列出各取值的业务含义。
4. 嵌套对象默认行内展开（保持自包含）；同一结构被引用 2 次以上才提到 `$defs`。
5. 数组必须有 `items`；元组用 `prefixItems`，**不要**把 `items` 写成数组（那是 draft-07 写法）。
6. `required` 只放本层字段名，且必须在同级 `properties` 中存在。
7. `additionalProperties` 显式写 `false`；若同时用了 `allOf` 组合，改用 `unevaluatedProperties: false`，否则子 Schema 会把彼此声明的字段判为多余。
8. 只写有依据的数字约束。描述没说长度，就不加 `minLength` / `maxLength`。

**2020-12 与 draft-07 的改写对照**（写错就是无效 Schema）：

| 用途 | draft-07（禁止） | 2020-12（必须） |
|------|------------------|-----------------|
| 复用定义 | `definitions` | `$defs` |
| 元组 | `items: [{...}, {...}]` | `prefixItems: [{...}], items: false` |
| 属性依赖 | `dependencies` | `dependentRequired` / `dependentSchemas` |
| 开区间 | `minimum: 5, exclusiveMinimum: true` | `exclusiveMinimum: 5`（数值） |
| 组合后封闭 | `additionalProperties: false` | `unevaluatedProperties: false` |

### 步骤 4 —— 生成示例数据

**必须真的能通过步骤 3 的 Schema**，不是「看起来像」。

| 字段类型 | 取值策略 |
|----------|----------|
| `string` + `email` | `"zhangsan@example.com"` |
| `string` + `uri` | `"https://example.com/profile/zhangsan"` |
| `string` + `date` | `"2026-04-16"` |
| `string` + `date-time` | `"2026-04-16T14:23:51+08:00"`（带时区） |
| `string` + `uuid` | 合法 UUID v4 形态 |
| `string` + `enum` | 取第一个枚举值（语义最典型那个） |
| `string` + `pattern` | **先构造匹配串再填**，如 `^ORD-\d{8}-\d{6}$` ⇒ `"ORD-20260416-000128"` |
| `string` 普通 | 贴合语义的中文值（`"张明"`、`"Cherry 红轴机械键盘"`） |
| `integer` | 落在区间内的整数 |
| `number` | 两位小数，满足 `multipleOf` |
| `boolean` | `true` |
| `array` | 2-3 个元素（若 `minItems` 更大则取 `minItems`） |
| `object` | 递归生成，含全部 `required` 字段 |

三条禁令：不许用 `"test"` / `"foo"` / `"123"` 这类占位值；不许省略 `required` 字段；不许出现 `additionalProperties: false` 之外的未声明字段。

### 步骤 5 —— 输出校验说明表

按 JSON 路径逐行展开，嵌套字段用 `parent.child`、数组元素用 `items[]`：

```markdown
| 字段路径 | 类型 | 必填 | 约束 | 说明 |
|----------|------|------|------|------|
| username | string | 是 | 2-20 字符 | 登录与显示名 |
| items[] | array | 是 | 至少 1 项 | 商品明细 |
| payment.method | string | 支付后必填 | enum: wechat_pay / alipay / bank_card | 支付方式 |
```

### 固定输出格式

每次执行输出三段，顺序不变，段间空行：

1. `### JSON Schema` + ```json 代码块
2. `### 示例数据` + ```json 代码块
3. `### 校验说明` + Markdown 表格

若步骤 0 判定为「带假设开工」，在三段之后追加 `### 待确认假设`，逐条列出假设项。**不要**把假设混进 Schema 注释里（JSON 不支持注释）。

## 输入输出约束

### 输入形态

**形态 A —— 自然语言**：

```
用户注册表单：用户名（必填，2-20 字符）、邮箱（必填）、密码（必填，至少 8 位，
需含字母与数字）、年龄（可选，0-150）、性别（男/女/保密，默认保密）、
兴趣标签（字符串数组，可选，最多 10 个且唯一）
```

**形态 B —— 字段清单**：

```
实体：用户注册
- username：string，必填，2-20 字符
- email：string，必填，email 格式
- password：string，必填，至少 8 位
```

**形态 C —— 存量 JSON 反推**：给一段真实样本，反推结构。此时必须做两件事：① 把样本里未出现的可选字段也补进来（否则 Schema 会过宽）；② 把「样本恰好是这种类型」升级为「语义上应该是这种类型」，并注明升级依据。

三种形态可混用。混合输入时以字段清单为准，自然语言用于补充语义。

### 命名约束

| 项 | 约束 |
|----|------|
| 字段名 | camelCase，英文，语义明确，不用拼音、不用缩写（`qty` 除外，行业惯用） |
| 布尔字段 | `is` / `has` / `can` 前缀 |
| 时间字段 | `xxxAt` |
| 数组字段 | 复数名词；元素对象内部用单数语义（`items[]` 内是 `productId`） |
| `$id` | kebab-case，与 `title` 语义一致 |
| `title` / `description` | 简体中文，一句话，不带句号 |

### 输出约束

| 项 | 要求 |
|----|------|
| 规范版本 | 只输出 Draft 2020-12 |
| 文件形态 | 单文档自包含；`$ref` 只允许 `#/$defs/xxx` 或 `#` |
| 字段描述 | 覆盖率必须 100% |
| 示例有效性 | 必须通过自身 Schema（跑 `scripts/check_schema.py`） |
| 规模上限 | 单文件 ≤ 200 行；超出则拆分为多文件并在说明表中给出引用关系 |
| 语言 | 正文中文；Schema 关键字与字段名英文 |

### 硬性禁止

- 禁止输出 draft-07 关键字（`definitions`、数组形式 `items`、`dependencies`、布尔型 `exclusiveMinimum`）。
- 禁止 `$ref` 指向外部 URL 或外部文件。
- 禁止在 Schema 中写注释（JSON 无注释语法，用 `description`）。
- 禁止为了让示例通过而放宽 Schema —— **改示例，不改约束**。
- 禁止编造 `pattern` 后不验证；每个 `pattern` 都要能被 `re.compile` 且示例值能匹配。

## 示例模板

### 模板 1 —— 扁平对象：用户注册

**输入**：

> 生成用户注册表单的 JSON Schema。用户名（必填，2-20 字符）、邮箱（必填）、密码（必填，至少 8 位，需含字母与数字）、年龄（可选，0-150）、性别（男/女/保密，默认保密）、兴趣标签（字符串数组，可选，最多 10 个且唯一）。

**Schema**：

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.com/schemas/user-registration.json",
  "title": "用户注册表单",
  "description": "用户注册时提交的表单数据，包含登录凭据与偏好设置",
  "type": "object",
  "properties": {
    "username": {
      "type": "string",
      "description": "显示名称与登录名，2-20 个字符",
      "minLength": 2,
      "maxLength": 20
    },
    "email": {
      "type": "string",
      "description": "用于账号验证与通知的邮箱地址",
      "format": "email"
    },
    "password": {
      "type": "string",
      "description": "登录密码，至少 8 位且必须同时包含字母与数字",
      "minLength": 8,
      "pattern": "^(?=.*[A-Za-z])(?=.*\\d).+$"
    },
    "age": {
      "type": "integer",
      "description": "用户年龄，单位岁",
      "minimum": 0,
      "maximum": 150
    },
    "gender": {
      "type": "string",
      "description": "性别：male 男 / female 女 / undisclosed 保密",
      "enum": ["male", "female", "undisclosed"],
      "default": "undisclosed"
    },
    "interests": {
      "type": "array",
      "description": "兴趣标签，最多 10 个且不可重复",
      "items": {
        "type": "string",
        "description": "单个兴趣标签",
        "minLength": 1,
        "maxLength": 50
      },
      "maxItems": 10,
      "uniqueItems": true
    }
  },
  "required": ["username", "email", "password"],
  "additionalProperties": false
}
```

**示例数据**：

```json
{
  "username": "zhangsan2026",
  "email": "zhangsan@example.com",
  "password": "Secure8pass",
  "age": 28,
  "gender": "male",
  "interests": ["编程", "摄影", "篮球"]
}
```

**校验说明**：

| 字段路径 | 类型 | 必填 | 约束 | 说明 |
|----------|------|------|------|------|
| username | string | 是 | 2-20 字符 | 登录与显示名 |
| email | string | 是 | email 格式 | 验证与通知渠道 |
| password | string | 是 | ≥ 8 位，且含字母与数字 | 登录密码，明文不落库 |
| age | integer | 否 | 0 - 150 | 用户年龄 |
| gender | string | 否 | enum: male / female / undisclosed，默认 undisclosed | 性别 |
| interests | array&lt;string&gt; | 否 | ≤ 10 项且唯一，每项 1-50 字符 | 兴趣标签 |

**本例考点**：`pattern` 用了前瞻断言表达「同时含字母与数字」；`default` 只是注解，**不会**在校验时自动填充 —— 这一点必须在说明里讲清，否则前端会以为后端会补默认值。

### 模板 2 —— 嵌套对象 + 对象数组：电商订单

**输入**：

> 电商订单：订单号（必填，格式 ORD-YYYYMMDD-6 位流水号）、创建时间（必填）、状态（待支付/已支付/已发货/已完成/已取消）、客户信息（userId + 昵称，必填）、商品列表（至少 1 项，每项含商品 ID、名称、单价、数量、小计）、收货地址（省/市/区 + 详细地址 + 邮编 + 收件人 + 手机号，必填）、支付信息（支付方式、交易号、支付时间 —— 支付后必填）、金额明细（商品总额、运费、折扣、实付，全部必填）、备注（可选，最多 200 字符）。

**Schema**：

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.com/schemas/ecommerce-order.json",
  "title": "电商订单",
  "description": "完整订单结构，涵盖客户、商品明细、收货地址、支付与金额",
  "type": "object",
  "properties": {
    "orderId": {
      "type": "string",
      "description": "订单号，格式 ORD-YYYYMMDD-NNNNNN",
      "pattern": "^ORD-\\d{8}-\\d{6}$"
    },
    "createdAt": {
      "type": "string",
      "description": "订单创建时间，RFC 3339 带时区",
      "format": "date-time"
    },
    "status": {
      "type": "string",
      "description": "订单状态：pending 待支付 / paid 已支付 / shipped 已发货 / completed 已完成 / cancelled 已取消",
      "enum": ["pending", "paid", "shipped", "completed", "cancelled"]
    },
    "customer": {
      "type": "object",
      "description": "下单客户信息",
      "properties": {
        "userId": { "type": "string", "description": "用户唯一 ID" },
        "nickname": { "type": "string", "description": "显示昵称" }
      },
      "required": ["userId", "nickname"],
      "additionalProperties": false
    },
    "items": {
      "type": "array",
      "description": "商品明细，至少一项",
      "minItems": 1,
      "items": {
        "type": "object",
        "description": "单行商品",
        "properties": {
          "productId": { "type": "string", "description": "商品唯一 ID" },
          "productName": { "type": "string", "description": "商品名称" },
          "unitPrice": {
            "type": "number",
            "description": "单价，单位元",
            "minimum": 0,
            "multipleOf": 0.01
          },
          "quantity": {
            "type": "integer",
            "description": "购买数量",
            "minimum": 1
          },
          "subtotal": {
            "type": "number",
            "description": "行小计，等于 unitPrice × quantity",
            "minimum": 0,
            "multipleOf": 0.01
          }
        },
        "required": ["productId", "productName", "unitPrice", "quantity", "subtotal"],
        "additionalProperties": false
      }
    },
    "shippingAddress": {
      "type": "object",
      "description": "收货地址",
      "properties": {
        "province": { "type": "string", "description": "省份" },
        "city": { "type": "string", "description": "城市" },
        "district": { "type": "string", "description": "区或县" },
        "detail": { "type": "string", "description": "详细地址", "maxLength": 200 },
        "zipCode": { "type": "string", "description": "邮政编码，6 位数字", "pattern": "^\\d{6}$" },
        "recipientName": { "type": "string", "description": "收件人姓名" },
        "phoneNumber": { "type": "string", "description": "收件人手机号", "pattern": "^1[3-9]\\d{9}$" }
      },
      "required": ["province", "city", "district", "detail", "recipientName", "phoneNumber"],
      "additionalProperties": false
    },
    "payment": {
      "type": "object",
      "description": "支付信息，支付完成后必填；待支付订单可整体省略",
      "properties": {
        "method": {
          "type": "string",
          "description": "支付方式：wechat_pay 微信支付 / alipay 支付宝 / bank_card 银行卡",
          "enum": ["wechat_pay", "alipay", "bank_card"]
        },
        "transactionId": { "type": "string", "description": "支付渠道交易号" },
        "paidAt": { "type": "string", "description": "支付完成时间", "format": "date-time" }
      },
      "required": ["method", "transactionId", "paidAt"],
      "additionalProperties": false
    },
    "pricing": {
      "type": "object",
      "description": "金额明细，单位元",
      "properties": {
        "itemsTotal": { "type": "number", "description": "商品总额", "minimum": 0, "multipleOf": 0.01 },
        "shippingFee": { "type": "number", "description": "运费", "minimum": 0, "multipleOf": 0.01 },
        "discount": { "type": "number", "description": "折扣金额", "minimum": 0, "multipleOf": 0.01 },
        "totalPaid": { "type": "number", "description": "实付金额", "minimum": 0, "multipleOf": 0.01 }
      },
      "required": ["itemsTotal", "shippingFee", "discount", "totalPaid"],
      "additionalProperties": false
    },
    "remark": {
      "type": "string",
      "description": "买家备注",
      "maxLength": 200
    }
  },
  "required": ["orderId", "createdAt", "status", "customer", "items", "shippingAddress", "pricing"],
  "additionalProperties": false
}
```

**示例数据**：

```json
{
  "orderId": "ORD-20260416-000128",
  "createdAt": "2026-04-16T14:23:51+08:00",
  "status": "paid",
  "customer": { "userId": "U20230001", "nickname": "小明" },
  "items": [
    {
      "productId": "SKU-8821",
      "productName": "Cherry 红轴机械键盘 87 键",
      "unitPrice": 459.00,
      "quantity": 1,
      "subtotal": 459.00
    },
    {
      "productId": "SKU-3356",
      "productName": "胡桃木桌面收纳架",
      "unitPrice": 79.90,
      "quantity": 2,
      "subtotal": 159.80
    }
  ],
  "shippingAddress": {
    "province": "广东省",
    "city": "深圳市",
    "district": "南山区",
    "detail": "科技园南区 T3 栋 1205 室",
    "zipCode": "518000",
    "recipientName": "张明",
    "phoneNumber": "13800138001"
  },
  "payment": {
    "method": "wechat_pay",
    "transactionId": "WX2026041614235100001",
    "paidAt": "2026-04-16T14:25:03+08:00"
  },
  "pricing": {
    "itemsTotal": 618.80,
    "shippingFee": 0.00,
    "discount": 30.00,
    "totalPaid": 588.80
  },
  "remark": "键盘请选黑色，尽量周末送达"
}
```

**校验说明**：

| 字段路径 | 类型 | 必填 | 约束 | 说明 |
|----------|------|------|------|------|
| orderId | string | 是 | `^ORD-\d{8}-\d{6}$` | 订单唯一编号 |
| createdAt | string | 是 | date-time | 创建时间 |
| status | string | 是 | enum: pending / paid / shipped / completed / cancelled | 订单状态 |
| customer.userId | string | 是 | —— | 用户 ID |
| customer.nickname | string | 是 | —— | 显示昵称 |
| items[] | array | 是 | ≥ 1 项 | 商品明细 |
| items[].unitPrice | number | 是 | ≥ 0，精度 0.01 | 单价（元） |
| items[].quantity | integer | 是 | ≥ 1 | 购买数量 |
| items[].subtotal | number | 是 | ≥ 0，精度 0.01 | 行小计 |
| shippingAddress.* | object | 是 | 见子字段 | 收货地址 |
| shippingAddress.phoneNumber | string | 是 | `^1[3-9]\d{9}$` | 手机号 |
| payment | object | 支付后必填 | 内部 3 字段全必填 | 支付信息 |
| pricing.totalPaid | number | 是 | ≥ 0 | 实付金额 |
| remark | string | 否 | ≤ 200 字符 | 买家备注 |

**本例考点**：

- `subtotal` 与 `unitPrice × quantity` 的相等关系，**JSON Schema 表达不了**，只能写进 `description` 交由业务层校验。遇到这类需求要在说明里明说，不要假装约束住了。
- `payment` 是「支付后必填」，`required` 里不能放它。真正要强制时用 `if/then`：

```json
{
  "if": { "properties": { "status": { "const": "paid" } }, "required": ["status"] },
  "then": { "required": ["payment"] }
}
```

### 模板 3 —— 顶层数组 + `$defs` + 条件分派：审计日志

**输入**：

> 审计日志按批次上报。每条事件含事件 ID（UUID）、发生时间、动作（create/update/delete）、操作者、被操作资源 ID。操作者分两类：人类用户（用户 ID + 来源 IP）或系统服务（服务名 + 链路 ID），两类必有且仅有一类字段组合成立。单批 1-100 条。

**Schema**：

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.com/schemas/audit-log.json",
  "title": "审计日志批次",
  "description": "按批次上报的审计事件集合，单批 1-100 条",
  "type": "array",
  "minItems": 1,
  "maxItems": 100,
  "items": { "$ref": "#/$defs/auditEvent" },
  "$defs": {
    "auditEvent": {
      "type": "object",
      "description": "单条审计事件",
      "properties": {
        "eventId": {
          "type": "string",
          "description": "事件唯一 ID，UUID v4",
          "format": "uuid"
        },
        "occurredAt": {
          "type": "string",
          "description": "事件发生时间，RFC 3339 带时区",
          "format": "date-time"
        },
        "action": {
          "type": "string",
          "description": "动作：create 新建 / update 修改 / delete 删除",
          "enum": ["create", "update", "delete"]
        },
        "actor": {
          "description": "操作者，人类用户或系统服务，二选一",
          "oneOf": [
            { "$ref": "#/$defs/humanActor" },
            { "$ref": "#/$defs/serviceActor" }
          ]
        },
        "target": {
          "type": "string",
          "description": "被操作资源的类型化 ID，形如 order:ORD-20260416-000128"
        },
        "diff": {
          "type": "object",
          "description": "变更快照，delete 动作可省略",
          "properties": {
            "before": { "type": "object", "description": "变更前字段快照" },
            "after": { "type": "object", "description": "变更后字段快照" }
          },
          "additionalProperties": false
        }
      },
      "required": ["eventId", "occurredAt", "action", "actor", "target"],
      "dependentRequired": { "diff": ["after"] },
      "additionalProperties": false
    },
    "humanActor": {
      "type": "object",
      "description": "人类用户操作者",
      "properties": {
        "principalType": { "type": "string", "description": "固定为 user", "const": "user" },
        "userId": { "type": "string", "description": "用户 ID" },
        "ipAddress": { "type": "string", "description": "来源 IP", "format": "ipv4" }
      },
      "required": ["principalType", "userId"],
      "additionalProperties": false
    },
    "serviceActor": {
      "type": "object",
      "description": "系统服务操作者",
      "properties": {
        "principalType": { "type": "string", "description": "固定为 service", "const": "service" },
        "serviceName": { "type": "string", "description": "服务名" },
        "traceId": { "type": "string", "description": "链路追踪 ID" }
      },
      "required": ["principalType", "serviceName"],
      "additionalProperties": false
    }
  }
}
```

**示例数据**：

```json
[
  {
    "eventId": "3f2b8c1e-9a4d-4e6b-8c2f-1d5a7e9b0c34",
    "occurredAt": "2026-04-16T09:12:35+08:00",
    "action": "update",
    "actor": {
      "principalType": "user",
      "userId": "U20230001",
      "ipAddress": "203.0.113.42"
    },
    "target": "order:ORD-20260416-000128",
    "diff": {
      "before": { "status": "pending" },
      "after": { "status": "paid" }
    }
  },
  {
    "eventId": "8c1d4a72-0b3e-4f5a-9d6c-2e7b8a1f3d90",
    "occurredAt": "2026-04-16T09:12:36+08:00",
    "action": "create",
    "actor": {
      "principalType": "service",
      "serviceName": "order-settlement",
      "traceId": "b7e2c9d14f0a4c3e"
    },
    "target": "invoice:INV-20260416-000045"
  }
]
```

**校验说明**：

| 字段路径 | 类型 | 必填 | 约束 | 说明 |
|----------|------|------|------|------|
| [ ] | array | 是 | 1-100 项 | 日志批次 |
| [].eventId | string | 是 | uuid | 事件唯一 ID |
| [].occurredAt | string | 是 | date-time | 发生时间 |
| [].action | string | 是 | enum: create / update / delete | 动作类型 |
| [].actor | object | 是 | oneOf: humanActor / serviceActor | 操作者 |
| [].actor.principalType | string | 是 | const: user 或 service | 判别标志 |
| [].diff | object | 否 | 出现 `diff` 时必须带 `after` | 变更快照 |
| [].target | string | 是 | —— | 资源类型化 ID |

**本例考点**：

- `oneOf` 里的两个分支各带 `const` 判别字段（`principalType`），保证「恰好命中一个」，不会两个都过。
- `dependentRequired` 表达「有 `diff` 就必须有 `after`」，这是 2020-12 的写法，draft-07 得用 `dependencies`。
- 顶层是数组时，`items` 用 `$ref` 指向 `$defs`，这是唯一推荐的复用方式。

## 边界情况处理

### 描述不完整

| 情况 | 处理 |
|------|------|
| 未说明必填/可选 | 核心业务标识与关键字段默认必填，辅助字段默认可选，并在「待确认假设」中列出 |
| 未给长度限制 | **不加** `minLength` / `maxLength` |
| 未给数值范围 | 仅语义明确时加（年龄 0-150）；金额只加 `minimum: 0` |
| 类型不确定 | 先按字段名语义推断并标注；真的两可（如 `"code"` 可能是 string 也可能 number）才追问 |
| 中英混写 | 统一转 camelCase 英文，中文进 `description` |
| 未提 `additionalProperties` | 默认 `false` |

### 特殊类型表达

| 描述 | 写法 |
|------|------|
| 文件 / 图片 | `{"type": "string", "format": "uri"}` 存 URL；或 `contentEncoding: "base64"` |
| 任意类型 | `{}`（不写 `type`），并在 `description` 说明为何放开 |
| 字典 / 映射 | `{"type": "object", "additionalProperties": {"type": "string"}}` |
| 元组（固定长度异构） | `prefixItems: [...]` + `items: false` + `minItems`/`maxItems` 锁死长度 |
| 联合类型 | 优先 `oneOf`（互斥）；允许重叠时用 `anyOf` |
| 递归结构（树、嵌套评论） | `{"$ref": "#/$defs/node"}` 自引用，`children` 的 `items` 指向自身 |
| 可为 null | `{"type": ["string", "null"]}`，不要用 `oneOf` 包 null 分支 |

递归树的最小形态：

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.com/schemas/comment-tree.json",
  "title": "评论树",
  "description": "支持任意层嵌套的评论结构",
  "type": "object",
  "properties": {
    "content": { "type": "string", "description": "评论正文" },
    "children": {
      "type": "array",
      "description": "子回复",
      "items": { "$ref": "#" }
    }
  },
  "required": ["content"],
  "additionalProperties": false
}
```

### 大型 Schema（30+ 字段或 4+ 层嵌套）

1. 先出顶层骨架，复杂子对象用 `$ref: "#/$defs/xxx"` 占位。
2. 再逐个展开 `$defs`，每个 `$defs` 条目自成闭包。
3. 被引用 ≥ 2 次的子结构必须进 `$defs`；只引用 1 次的保持行内。
4. 超过 200 行拆文件，在说明表后给出文件清单与引用关系。

### 容易踩的坑

| 坑 | 现象 | 正确做法 |
|----|------|----------|
| `format` 不生效 | 邮箱字段 `"abc"` 竟然通过 | 2020-12 中 `format` 默认只是**注解**；要真校验需启用 format-assertion 词汇表，或补 `pattern` |
| 过度约束 | 合法数据被拒 | 无依据的数字不写；宁可后续收紧 |
| 浮点精度 | `0.1 + 0.2` 类金额校验翻车 | 金额用 `multipleOf: 0.01`，比较时留容差；高精度场景改用整数分 |
| `allOf` + `additionalProperties` | 组合后所有字段都被判多余 | 改用 `unevaluatedProperties: false` |
| `default` 被当成自动填充 | 前端不发字段，后端也没补 | `default` 仅注解；填充逻辑必须在代码里实现 |
| 中文键名 | `{"用户名": ...}` 通过校验但难以对接 | 键名一律英文，中文只进 `description` |
| `pattern` 未转义 | `^\d{6}$` 写成 `^d{6}$` | JSON 里反斜杠要双写：`"^\\d{6}$"` |

## 自检门禁

产出后必须跑一次随附脚本，**跑不过不许交付**。

### 快速开始

```bash
# 双闸门：结构规范 + 示例数据
python scripts/check_schema.py schema.json example.json

# 机器可读输出（CI / Agent 用）
python scripts/check_schema.py schema.json example.json --json

# 用例驱动：跑 cases/pass 与 cases/fail 下所有用例并比对期望
python scripts/check_schema.py --cases cases
python scripts/check_schema.py --cases cases --json

# 证明门禁本身会失败：11 个内联坏样本必须全部被拦住
python scripts/check_schema.py --selftest
```

### 可执行契约

| 项 | 约定 |
|----|------|
| 退出码 `0` | 通过 |
| 退出码 `1` | 存在 ERROR（校验失败），`failures` 非空 |
| 退出码 `2` | 参数或 IO 错误，输入无法读取 |
| stdout | 默认人读文本；加 `--json` 时只输出单段 JSON，不混其他内容 |
| stderr | 只放错误原因，不参与判定 |

`--json` 输出结构：

```json
{
  "status": "pass",
  "exitCode": 0,
  "failures": [
    { "path": "$.username", "rule": "length", "message": "长度 1 小于 minLength 2" }
  ],
  "warnings": [],
  "summary": { "errors": 0, "warnings": 0, "checkedExample": true }
}
```

`path` 为 JSON 路径（`$` 根、`$.a.b`、`$[0]`、`$.a[1].b`）；`rule` 取自固定枚举，可按规则聚合统计：

| 闸门 | rule 取值 |
|------|-----------|
| 结构闸门 | `schema-version` `root-metadata` `no-sub-id` `legacy-keyword` `field-naming` `field-description` `object-additional-properties` `required-unknown-field` `required-empty` `array-items` `items-array-form` `range-inconsistent` `exclusive-boolean` `multiple-of` `enum-shape` `pattern-invalid` `format-unknown` `ref-unsupported` `ref-unresolved` `schema-shape` |
| 数据闸门 | `type-mismatch` `required-missing` `additional-property` `enum-mismatch` `const-mismatch` `length` `numeric-range` `items-count` `unique-items` `pattern-mismatch` `format-mismatch` `combinator` `ref-circular` |

### 用例组织

内联自检（`--selftest`）是零依赖冒烟，改规则时跑；`cases/` 是**可被外部扩充**的回归集，接受 PR 式新增。

```text
cases/
├── pass/
│   ├── minimal-object.json          # 最小合法对象
│   └── defs-oneof.json              # $defs + oneOf 恰好命中一个分支
└── fail/
    ├── defs-hidden-invalid.json     # 假通过专项：顶层合法、$defs 内非法
    ├── field-naming-kebab.json      # 字段名非 camelCase
    ├── ref-external.json            # 跨文件 $ref
    ├── ref-circular.json            # 循环 $ref 不收敛
    ├── legacy-definitions.json      # draft-07 关键字残留
    └── array-without-items.json     # 数组缺 items
```

单个用例文件的结构固定：

```json
{
  "description": "这条用例在验什么",
  "expect": "pass",
  "expectRule": "field-naming",
  "schema": {},
  "example": {}
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `description` | 是 | 一句话说清意图，失败时人靠它定位 |
| `expect` | 否 | `pass` / `fail`；缺省按所在目录（`pass/` 或 `fail/`）推断 |
| `expectRule` | fail 用例建议填 | 断言命中的 rule，防止「因为别的原因失败」被当成通过 |
| `schema` | 是 | 被测 Schema |
| `example` | 否 | 提供则同时跑数据闸门 |

**假通过专项**：`cases/fail/defs-hidden-invalid.json` 是顶层完全合法、示例也能通过数据闸门的样本，只有 `$defs` 内一个字段缺 `description`。若它返回 `pass`，说明校验没有递归到 `$defs` —— **视为门禁缺陷，先修脚本**，不要把该用例的期望改成 pass。

### 实现约束

以下四条是踩过的坑固化成的契约，不是建议。改脚本时必须守住。

1. **失败条目必须具名访问**。用 `@dataclass(frozen=True)` 定义 `Finding(path, rule, severity, message)`，禁止 tuple / list + 下标。曾因列表推导里复用 `_` 变量，使 `severity == "error"` 实际比较的是 `message`，导致 11 个坏样本全部漏判 —— 而这**只在自检自身跑起来时才暴露**。
2. **severity 判断只写在具名属性上**（`f.severity == "error"`），不在推导中引用循环变量之外的临时名。
3. **不硬编码临时目录**。需要落盘时用 `tempfile.TemporaryDirectory()`，禁止写死 `/tmp`、`%TEMP%`、`C:/Users/...`。此前示例抽取脚本死在 Windows 把 `/tmp` 解析成 `\tmp`。
4. **stderr 只放诊断，不参与判定**。判定只看退出码与 stdout 的 JSON；`--json` 模式下 stdout 必须是一段合法 JSON，不夹带日志。

### 边界与豁免

| 情况 | 门禁行为 |
|------|----------|
| 跨文件 `$ref`（`./common.json#/...`） | 报 `ref-unsupported`，**不静默跳过** —— 产出必须自包含单文档 |
| 循环 `$ref`（未消耗数据就回到同一路径） | 报 `ref-circular`，不会无限递归 |
| 字段名判定范围 | 只作用于 `properties` 的键；`$defs`、`patternProperties`、`additionalProperties` 的键**豁免** |
| `description` 中的尖括号 | **不豁免** —— 为简化规则，一律改用 `[placeholder]` 或反引号 |
| 数字开头 / 连续连字符 / 结尾连字符的字段名 | 一律 `field-naming` 报错，不做特例放行 |

### 脚本覆盖不到、必须人工确认的四点

1. `description` 是否说清了**业务含义**，而不只是复述字段名。
2. 枚举值的业务解释是否完整（每个取值都要有中文说明）。
3. 示例值是否语义真实（能否放进真实系统的日志里而不违和）。
4. 「待确认假设」是否列全（尤其是默认必填/可选这一判断）。

### 失败处理

只写「失败了怎么修」，不写「什么算通过」（后者见下一节，避免两处各写一遍）。

| 失败项 | 动作 |
|--------|------|
| `field-naming` | 改成 camelCase，同步更新示例数据与校验说明表 |
| `field-description` | 补业务含义，不要写「字段名 + 类型」这种同义反复 |
| `required-unknown-field` | 核对 `required` 与同级 `properties` 的拼写 |
| `array-items` | 补 `items`（或元组场景补 `prefixItems` + `items: false`） |
| `ref-unsupported` / `ref-unresolved` | 跨文件引用改行内或 `$defs`；路径写错就修路径 |
| `ref-circular` | 把递归子节点指向 `$defs` 里的同一份定义，不要用 `#` 自引用空转 |
| `type-mismatch` / `additional-property` | **改示例，不改约束** —— 放宽 Schema 让示例通过属于作弊 |
| `legacy-keyword` | 按步骤 3 的改写对照表换成 2020-12 关键字 |
| 用例期望错配（`--cases` 报 FAIL） | 看 detail 里的 `rule`：rule 正确 ⇒ 期望写错了，改期望；rule 不对 ⇒ 脚本有缺陷，修脚本 |
| `fail/` 用例返回 `pass` | 假通过。补用例 + 修脚本，**不许把期望改成 pass 了事** |
| `--selftest` 不过 | 视作门禁自身缺陷，先修脚本，再谈产出 |

### 验收标准

只写可判定的谓词，与上表不重复。全部成立才算交付：

- [ ] `check_schema.py schema.json example.json` 退出码为 `0`
- [ ] `--selftest` 的 11 例全部 `[PASS]`
- [ ] `--cases cases` 退出码为 `0`，且 `pass/` 全返回 pass、`fail/` 全返回 fail
- [ ] 假通过专项 `defs-hidden-invalid` 返回 `fail`（rule = `field-description`）
- [ ] 期望错配探针（把坏 schema 的 `expect` 写成 `pass`）必须被判 FAIL —— 证明用例框架不是恒绿
- [ ] `--json` 输出为单段合法 JSON，`summary.errors` 为 `0` 且 `checkedExample` 为 `true`
- [ ] `SKILL.md` frontmatter 的 `name` / `description` / `agent_created` 三项齐全
- [ ] 全量产出的字段名均为 camelCase，`description` 无尖括号

## 常见问题

**Q：生成 2020-12 的 Schema，Ajv 应该怎么初始化？**

`new Ajv()` 默认是 draft-07，编译 2020-12 的 Schema 会报 `no schema with key or ref`。必须用 2020 入口：

```javascript
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const ajv = new Ajv2020({ allErrors: true, strict: false });
addFormats(ajv);
const validate = ajv.compile(schema);
if (!validate(example)) console.error(validate.errors);
```

**Q：`format: "email"` 到底会不会拦住非法邮箱？**

2020-12 把 `format` 定为注解（annotation）语义，是否断言取决于实现启用的词汇表。Ajv 需 `ajv-formats` 且默认开启；python-jsonschema 默认不校验 format。**需要强约束时同时写 `pattern`。**

**Q：能直接用于 OpenAPI 3.1 吗？**

可以。OpenAPI 3.1 的 Schema Object 基于 JSON Schema 2020-12，`$defs`、`prefixItems`、`dependentRequired` 都能用。差异在于 OAS 追加了 `discriminator`、`example` 等自有字段，且 `nullable` 不是标准关键字（用 `type: ["string", "null"]`）。

**Q：用户给的是 draft-07 的旧 Schema，要迁移怎么办？**

按步骤 3 的对照表逐项替换：`definitions` → `$defs`、数组 `items` → `prefixItems`、`dependencies` → `dependentRequired`/`dependentSchemas`、布尔 `exclusiveMinimum` → 数值、`additionalProperties: false` 在 `allOf` 场景 → `unevaluatedProperties: false`。改完跑一次自检门禁。

**Q：字段太多，输出会很长怎么办？**

按「大型 Schema」四步走：骨架 → `$defs` 展开 → 合并重复结构 → 超 200 行拆文件。不要为了短而删 `description`。

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.2 | 2026-10-29 | 失败条目改 `@dataclass(frozen=True) Finding`，消灭 8 处位置下标访问（曾因推导里复用 `_` 导致 severity 判定比较的是 message）；新增 `--cases` 用例驱动与 `cases/pass` + `cases/fail` 回归集（含 `defs-hidden-invalid` 假通过专项）；新增「实现约束」四条（具名访问 / 禁硬编码临时目录 / stderr 不参与判定）；验收标准改为可断言的 checkbox 清单 |
| 1.0.1 | 2026-10-29 | 补齐可执行契约：退出码 0/1/2、`--json` 输出结构、`rule` 固定枚举；门禁新增 `field-naming`（camelCase 判定）与 `ref-unsupported` / `ref-circular` 边界；自检样本从 5 例扩到 11 例；把「失败处理」与「验收标准」拆成两节，删除重复的字段级描述 |
| 1.0.0 | 2026-10-29 | 首个发布版本：六步工作流、三个示例模板、2020-12 改写对照表、`check_schema.py` 双闸门自检 |

**规则变更必须在此登记**（含改了哪条 rule、为什么改）。未登记的规则调整一律视为门禁漂移，不予采纳。

## 许可证

MIT License
