# LangChain 旅游规划智能体

这是一个用于“智能体架构与开发流程”实验的课程项目。项目基于 Python、Flask、LangChain 和 DeepSeek API，实现了一个可以进行自然语言旅游规划的 Agent：理解需求、拆解任务、调用模型、选择外部工具、汇总结果，并在网页端展示最终方案和执行过程。

项目参考了本地下载的飞桨 AI Studio 教程《【LangChain+文心大模型】构建旅游出行规划智能体》，但当前版本已经扩展为带 Web UI、多轮会话、流式执行过程、真实地图/天气/交通工具和结构化卡片展示的本地演示系统。

## 当前状态

当前项目适合用于：

- 课程实验验收
- 本地演示 LangChain Agent 工作流
- 继续打磨为简历项目或面试展示项目

核心能力已经完成：

- DeepSeek 普通模式和深度思考模式切换
- LangChain Agent 自主选择工具
- Flask Web 聊天界面
- SSE 流式返回 Agent 执行过程
- SQLite 历史会话持久化
- Markdown 回答 + 结构化卡片双输出
- 高德地图、和风天气、Aviationstack、12306-MCP 等外部数据源接入

当前工具数量：

- 15 个核心 Python 工具
- 3 个可选 12306 火车票工具
- Node.js / npx 不可用时，12306 工具自动降级，不影响其他功能

## 技术栈

- Python
- Flask
- LangChain
- `langchain-openai` OpenAI-compatible 接口
- DeepSeek API
- 高德地图 Web 服务 API
- 和风天气 API
- Aviationstack API
- 12306-MCP
- SQLite
- 原生 HTML / CSS / JavaScript
- SSE 流式通信

推荐解释器：

```powershell
C:\Users\BaoXinJie\anaconda3\python.exe
```

## 运行方式

安装依赖：

```powershell
C:\Users\BaoXinJie\anaconda3\python.exe -m pip install -r requirements.txt
```

启动 Web 项目：

```powershell
C:\Users\BaoXinJie\anaconda3\python.exe app.py
```

浏览器访问：

```text
http://127.0.0.1:5000
```

命令行普通模式：

```powershell
C:\Users\BaoXinJie\anaconda3\python.exe run.py -q "我明天从郑州去杭州，玩3天"
```

命令行深度思考模式：

```powershell
C:\Users\BaoXinJie\anaconda3\python.exe run.py --thinking -q "我明天从郑州去杭州，玩3天"
```

命令行离线演示：

```powershell
C:\Users\BaoXinJie\anaconda3\python.exe run.py --offline-demo -q "我明天从郑州去杭州，玩3天"
```

离线演示不会调用 DeepSeek，只用于验证页面、工具链和卡片渲染流程。

## 环境变量

复制模板：

```powershell
Copy-Item .env.example .env
```

`.env` 需要配置：

```text
LLM_API_KEY=你的 DeepSeek API Key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
LLM_THINKING_MODEL=deepseek-v4-pro
LLM_TEMPERATURE=0.3
LLM_TIMEOUT=90

AMAP_API_KEY=你的高德地图 Web 服务 Key
QWEATHER_API_KEY=你的和风天气 API Key
QWEATHER_API_HOST=你的和风天气专属 API Host
AVIATIONSTACK_API_KEY=你的 Aviationstack API Key
```

注意：

- `.env` 包含真实密钥，不要提交到公开仓库。
- DeepSeek 控制台没有请求记录时，先检查前端是否开启了“离线演示”。
- 和风天气空气质量和天气预警接口可能需要账号权限，接口不可用时工具会降级，不会中断 Agent。
- Aviationstack 当前只用于航班时刻/状态查询，不提供真实机票价格。
- 12306 工具需要本机 Node.js / npx，首次调用可能较慢。

## 项目结构

```text
.
├── app.py                         # Flask 启动入口
├── web.py                         # Flask 路由、SSE、会话接口、高德前端代理
├── run.py                         # CLI 启动入口
├── requirements.txt               # Python 依赖
├── .env.example                   # 环境变量模板
├── README.md                      # 项目说明
├── EXPERIMENT_REPORT.md           # 实验报告材料
├── data/
│   └── travel_agent.db            # SQLite 数据库，运行后生成
├── static/
│   ├── app.js                     # 前端交互、SSE、卡片渲染、地图拖拽
│   └── styles.css                 # 页面样式
├── templates/
│   └── index.html                 # 页面模板
└── src/
    └── travel_agent/
        ├── agent.py               # Agent、提示词、trace、结构化 JSON 提取
        ├── cli.py                 # CLI 参数解析
        ├── config.py              # 配置读取
        ├── storage.py             # SQLite 会话持久化
        ├── tools.py               # 核心工具
        └── train_tools.py         # 12306-MCP 客户端和火车票工具
```

## Agent 架构

```text
用户输入
  -> Flask /api/chat/stream
  -> LangChain Agent
  -> DeepSeek LLM 理解需求
  -> LLM 决定是否调用工具
  -> 工具返回真实数据或降级结果
  -> LLM 汇总 Markdown 答案
  -> LLM 在答案末尾输出结构化 JSON
  -> 后端提取 structured_data 并去掉原始 JSON
  -> SSE 返回最终答案、trace 和 structured_data
  -> 前端渲染 Markdown、执行过程和卡片
```

这与固定流程脚本不同。固定流程通常写死“查天气 -> 查交通 -> 套模板”，而本项目由 LLM 根据用户问题自主判断是否需要天气、交通、火车、航班、POI、预算等工具。

## 核心功能

### Web 对话

- 多轮聊天
- 历史会话保存到 SQLite
- 刷新页面后恢复会话
- 可新建、切换、删除会话
- 支持停止当前流式请求

### 模型模式

- 普通模式：`deepseek-v4-flash`
- 深度思考模式：`deepseek-v4-pro`

当前深度思考模式是“更强模型 + 提示词层面的深度规划”，没有开启 DeepSeek API-level thinking。原因是 API-level thinking 在工具调用场景下需要维护 `reasoning_content` 回传，LangChain OpenAI-compatible 工具链暂未稳定处理该字段。为保证工具调用稳定，当前禁用了 API 原生 thinking。

### 执行过程可视化

前端会实时展示 Agent 的执行过程：

- 请求是否已发出
- 当前使用的模型
- 正在调用哪个工具
- 工具参数摘要
- 工具是否成功
- 工具耗时
- LLM token usage
- 异常步骤高亮
- 可导出执行报告 JSON

2026-05-18 已优化交互：

- 用户可以手动展开/折叠执行过程
- 手动折叠后不会被流式更新强制展开
- 展开状态下默认跟随最新阶段
- 用户拖动执行过程滚动条时，前端会短暂停止重绘，避免抢鼠标

### 结构化卡片

Agent 的最终回答末尾会输出 JSON，后端提取为 `structured_data`，前端渲染为卡片：

- 行程摘要
- 天气卡片
- 天气预警卡片
- 交通方案卡片
- 12306 中转分段卡片
- 每日行程时间轴
- 预算明细
- 出行提示
- POI 地点推荐卡片

如果模型没有输出合法 JSON，系统会自动回退到纯 Markdown，不影响回答展示。

### 地图和地点体验

高德地图相关能力：

- IP 默认城市识别
- 浏览器定位 + 高德逆地理编码
- 地点输入联想
- 地点解析
- 全城 POI 搜索
- 周边 POI 搜索
- 驾车路线
- 公交/地铁换乘
- 步行路线
- 骑行路线
- 距离矩阵
- 实时路况
- 高德 URI 地图链接
- 静态地图预览

2026-05-18 已完成的前端体验优化：

- 输入区增加“联想”开关，用户可关闭地点补全
- 点击联想候选时只替换当前地点片段，不再清空整句
- 地点推荐卡片和地图 marker 使用同一编号
- 所有推荐地点都会展示在该类别的静态地图上
- 静态地图使用更大图片和更大的展示窗口
- 地图支持鼠标按住拖拽，在有限范围内移动视角
- 静态地图无法像真实 JS 地图一样加载新瓦片，但足够用于观察推荐点的相对位置

## 工具列表

核心工具：

| 工具 | 数据源 | 说明 |
|---|---|---|
| `get_weather_info` | 和风 > 高德 > Open-Meteo | 天气查询，含回退 |
| `get_air_quality_info` | 和风 | 空气质量，权限不足时降级 |
| `get_weather_alerts` | 和风 | 天气预警，权限不足时降级 |
| `calculate_trip_budget` | 本地计算 | 预算估算 |
| `get_transport_advice` | 高德 | 驾车路线、距离、耗时、过路费 |
| `search_flight_options` | Aviationstack | 航班时刻/状态，不含票价 |
| `get_public_transit_plan` | 高德 | 公交/地铁换乘 |
| `get_walking_route` | 高德 | 步行路线 |
| `get_bicycling_route` | 高德 | 骑行路线 |
| `get_route_distance_matrix` | 高德 | 多起点距离/耗时对比 |
| `get_traffic_status` | 高德 | 实时路况 |
| `search_travel_pois` | 高德 | 全城景点、餐饮、商圈、酒店 POI |
| `search_nearby_pois` | 高德 | 指定地点周边 POI |
| `get_place_location` | 高德 | 地点解析和坐标 |
| `get_map_marker_link` | 高德 URI | 无 Key 地图链接 |

可选 12306 工具：

| 工具 | 数据源 | 说明 |
|---|---|---|
| `search_train_tickets` | 12306-MCP | 余票查询 |
| `search_interline_train_tickets` | 12306-MCP | 中转余票查询 |
| `get_train_route` | 12306-MCP | 车次经停站 |

## 主要接口

`web.py` 提供：

- `GET /`：Web 页面
- `GET /api/status`：模型和 API 状态
- `GET /api/conversations`：会话列表
- `GET /api/conversations/<id>/messages`：会话消息
- `DELETE /api/conversations/<id>`：删除会话
- `POST /api/chat`：非流式聊天，保留兼容
- `POST /api/chat/stream`：SSE 流式聊天，前端主要使用
- `GET /api/amap/ip-location`：高德 IP 定位代理
- `GET /api/amap/reverse-geocode`：高德逆地理编码代理
- `GET /api/amap/input-tips`：高德输入提示代理
- `GET /api/amap/static-map`：高德静态地图代理

前端不直接暴露高德 API Key。

## 常用验证命令

Python 编译检查：

```powershell
C:\Users\BaoXinJie\anaconda3\python.exe -m compileall app.py web.py run.py src
```

前端语法检查：

```powershell
node --check static/app.js
```

状态接口：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5000/api/status
```

查看 5000 端口：

```powershell
Get-NetTCPConnection -LocalPort 5000 -State Listen
```

关闭当前项目进程：

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like '*web.py*' -or $_.CommandLine -like '*app.py*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

## 已知限制

- Flask 当前是开发服务器，只适合本地演示。
- DeepSeek API-level thinking 暂未开启，深度思考模式依赖 Pro 模型和提示词。
- 航班工具不提供真实票价。
- 酒店真实价格 API 暂未接入，当前不做真实酒店价格查询。
- 和风空气质量/天气预警依赖账号权限，403 时会降级。
- 高德静态地图是图片，不是真正交互式地图；当前支持拖动图片视角，但不能缩放或加载新瓦片。
- 12306-MCP 首次调用可能因 npx 下载或初始化而较慢。

## 今日工作记录（2026-05-18）

今天主要完成了 Phase 3 用户体验和高德地图展示方向的收尾：

- 修复输入联想空白条遮挡按钮的问题。
- 解释并优化地点联想逻辑。
- 增加“联想”开关，用户可关闭高德地点补全。
- 修复点击联想候选后输入框被整句清空的问题。
- 修复执行过程流式更新时强制展开、抢滚动条、抢鼠标的问题。
- 优化执行过程滚动策略：默认跟随最新输出，用户操作时暂停重绘。
- 清理交通卡片里的技术噪声，例如无意义状态、空时间、Aviationstack 说明等。
- 修复交通卡片分类错误，例如“驾车”被误判为“火车”。
- 修复高德静态地图多 marker 参数格式错误导致的破图。
- 给静态资源增加版本号，减少浏览器缓存导致的旧页面问题。
- 将 POI 地图改为“地图编号 + 卡片编号 + 图例”对应关系。
- 支持每个推荐类别的所有地点展示在静态地图上。
- 扩大静态地图图片和展示窗口。
- 增加静态地图拖拽视角能力，方便观察推荐点相对位置。
- 继续完成 Phase 3 的 3/4/5 方向：每日行程可根据 POI 坐标生成当天地点关系小地图；单点查询提示词进一步收敛，避免简单查询扩展为完整行程；结构化卡片底部新增数据可信度区域，汇总数据源和限制说明。
- 重启并验证项目多次，确认首页模板和静态资源版本生效。

## 后续优化路线

### 当前 Phase 可继续优化

这一阶段仍然建议围绕“功能和用户体验”继续，不优先做工程化测试：

1. **地图交互增强**
   - 当前是可拖拽静态图，已经比普通图片强一些。
   - 已支持更大静态图、拖拽视角、重置视角、打开地图图像。
   - 后续可在不接 JS API 的前提下继续加地图全屏预览、按类别切换地图。

2. **POI 推荐质量**
   - 已支持按评分、人均、名称排序。
   - 已支持按类型、高评分、低人均、可联系筛选。
   - 对餐饮、景点、商圈、住宿分别使用更精确的高德 typecode。
   - 后续可结合路线顺序，增加“离当天路线近”的推荐。

3. **行程与地图联动**
   - 已支持根据 POI 坐标匹配每日行程地点，并为 Day1 / Day2 等生成当天地点关系小地图。
   - 后续可把每日行程地图升级为真正路线 polyline，而不是地点关系图。
   - 交通方案卡片点击后展示该路线涉及的起终点。

4. **单点查询体验继续收敛**
   - 已强化提示词：航班、火车、天气、公交、周边 POI 等单点查询只填相关结构化字段。
   - 前端不再为 total=0 且无说明的预算 JSON 渲染空预算卡。
   - 后续可加入后端轻量意图分类，在进入 Agent 前给单点查询附加更强约束。

5. **数据可信度展示**
   - 已新增数据可信度卡片，汇总天气、交通、POI、预算等数据源。
   - 已对“航班不含票价”“预算为估算值”“预警接口可能受权限影响”等限制做统一说明。
   - 后续可在导出报告里进一步区分真实数据、估算数据、模型推断。

### Phase 4：真正的地图交互系统

目标是把当前“可拖拽静态地图”升级为真正地图应用。预计需要高德 JS API Key 和安全密钥。

- 高德 JS API 地图组件
- marker 与 POI 卡片双向联动
- 点击 marker 展开地点详情
- 卡片 hover 时高亮地图 marker
- 路线 polyline 展示
- 地图上切换步行、公交、驾车路线

### Phase 5：旅行方案编辑器

目标是让用户不仅能看方案，还能直接调整方案。

- 用户可拖动调整每日行程顺序
- 删除不喜欢的景点
- 替换餐饮或景点
- 一键让 Agent 根据修改后的行程重新规划
- 形成“Agent 生成 -> 用户编辑 -> Agent 修正”的闭环

### Phase 6：偏好系统与本地知识库

目标是让 Agent 更像个人旅行助手，而不是一次性问答工具。

- 出行节奏：轻松 / 标准 / 紧凑
- 偏好：美食 / 历史 / 自然 / 亲子 / 拍照
- 交通：公共交通 / 自驾 / 打车优先
- 预算：经济 / 舒适 / 高端
- 偏好保存到会话或本地设置
- 加入城市攻略、景点开放时间、避坑建议、实验说明文档等本地资料
- Agent 先检索本地知识库，再结合实时工具结果回答

### Phase 7：导出、展示与工程化

目标是把项目打磨成可公开展示和面试讲解的版本。

- 一键导出 Markdown / PDF / HTML 行程单
- 导出内容包含地图、每日路线、预算、交通方案、执行报告摘要
- README 增加截图和演示 GIF
- 补充 pytest、mock API、Dockerfile
- 梳理提交记录和 Demo 脚本

旧 Phase 4 中的工作量较大，因此已经拆分为 Phase 4-7，避免单阶段目标过宽。

## 简历描述参考

可以概括为：

> 基于 LangChain 和 DeepSeek 的智能旅行规划 Agent，支持多轮对话、SSE 流式执行过程可视化、SQLite 历史持久化和 18 个外部工具调用。系统接入高德地图、和风天气、Aviationstack 与 12306-MCP，具备天气、预警、空气质量、驾车、公交、步行、骑行、实时路况、航班、火车票、POI 搜索、周边搜索、地点解析和静态地图展示能力。前端将模型输出的结构化 JSON 渲染为天气、交通、预算、行程、POI 和地图卡片，并支持地点联想、默认出发地识别、Agent 执行报告导出等交互。
