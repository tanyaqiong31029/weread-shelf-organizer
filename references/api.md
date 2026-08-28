# 微信读书书架接口参考

> ⚠️ 这些是微信读书客户端内部使用的接口，非官方开放 API，随时可能变更。
> 仅供个人管理自己的书架使用，请控制调用频率（脚本已内置批间 0.4s 延迟与重试）。

## 认证

所有请求携带请求头（从本机客户端日志提取，见 `weread_shelf.py extract_cred()`）：

```
vid:  用户数字 ID（8 位左右）
skey: 会话密钥（8 字符左右，服务端约数天过期，客户端启动时自动续期）
v:    客户端版本号，如 10.2.1.87
User-Agent: WeRead/10.2.1 (iPad; iOS 26.5; Scale/2.00)
Content-Type: application/json
```

- Mac 客户端（App Store 版）日志目录：
  `~/Library/Containers/com.tencent.weread/Data/Documents/log/*.log`
  每次启动生成新日志，含 `skey = xxx; v = "x.x.x"; vid = xxx` 的账号信息 dump。
- skey 过期（HTTP 401 / errcode -2012）：重启客户端即可续期（脚本 `get_cred()` 已处理）。

## 书架同步

```
GET /shelf/sync?userFlag=0&synckey=&teenmode=0&album=1
```

关键返回：
- `books[]`：电子书条目（bookId/title/author/category/secret/finishReading/readUpdateTime…）
- `archive[]`：分组列表（name / archiveId / bookIds[]）
- `albums[]`：专辑/有声书（独立于 books）
- `mp`：文章收藏入口（非空即书架有 1 个"文章收藏"条目）

注意：`archive[]` 内的 `bookIds` 是分组从属关系的权威来源；`books[]` 条目本身不含 archiveId。

## 分组管理

### 移书入组 / 建组

```
POST /shelf/archive
{"bookIds": ["..."], "albumIds": [], "archiveId": <id 或 0>, "name": "分组名"}
```

- `archiveId: 0` → 创建新分组（返回新 archiveId）
- `archiveId: <已有 id>` → 将书批量移入该分组（单次建议 ≤40 本）
- 成功返回 `{"succ": 1}`
- 同一本书重复移入同组是幂等 no-op

### 删除分组

```
POST /shelf/deleteArchive
{"archiveId": <id>, "removeBooks": 0}
```

- `removeBooks: 0` → 只删分组，书籍保留在书架（**始终用 0**）
- `removeBooks: 1` → 连书一起移出书架（**禁用**）

## 错误码

| errcode | 含义 | 处理 |
|---|---|---|
| -2012 | 登录超时（skey 失效） | 重启客户端续期 |
| -2013 | 鉴权失败 | 凭据错误，重新提取 |
| -2003 | 参数缺失/无效 | 检查请求体 |
| -2014 | 请求过频 | 增大延迟，退避重试 |

## 已知边界

- 网页版 (weread.qq.com/web/*) **没有**分组管理接口，只有只读的
  `/web/shelf/sync`、`/web/shelf/archive/<id>` 查看页 —— 分组写操作必须走
  i.weread.qq.com 客户端接口。
- 官方开放平台（Agent API Gateway）目前全部接口只读，无分组写能力。
- 导入的第三方书籍（bookId 以 `CB_` 开头等）无平台分类，需按书名/作者定类。
- `归档`（archiveId=1）是系统内置分组，不要删除。
