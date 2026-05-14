# 实验十一：基于 LangChain 的旅游出行规划智能体

## 一、实验目标

本实验目标是理解智能体的基本架构，掌握使用 LangChain 开发智能体的流程。智能体不是单纯的问答程序，而是能够围绕用户目标完成“理解需求、拆解任务、调用工具、执行验证、输出结果”的自主系统。

## 二、主流智能体架构调研

目前常见智能体方案可以分为三类：

1. 代码开发框架：LangChain、LangGraph、AutoGen、CrewAI、LlamaIndex 等。
2. 低代码平台：Dify 等。
3. 无代码平台：Coze 等。

其中 LangChain 适合教学和原型开发，因为它提供了 LLM、Prompt、Tool、Agent 等完整组件，能清晰展示智能体如何把大模型和外部工具连接起来。

## 三、LangChain 优势

LangChain 的优势主要包括：

- 生态成熟，支持多种 LLM 和工具接入。
- Tool 封装简单，适合把普通 Python 函数变成智能体可调用能力。
- Agent 能根据用户输入自主选择工具，而不是固定执行流程。
- 兼容 OpenAI-style API，便于接入文心大模型、OpenAI 或其他兼容模型。
- 代码结构清晰，适合从实验扩展到真实应用。

## 四、环境配置

本项目使用本机 Anaconda Python：

```text
C:\Users\BaoXinJie\anaconda3\python.exe
Python 3.11.5
```

安装依赖：

```powershell
C:\Users\BaoXinJie\anaconda3\python.exe -m pip install -r requirements.txt
```

核心依赖：

```text
langchain
langchain-core
langchain-openai
requests
python-dotenv
tenacity
```

## 五、系统设计

本项目设计了一个旅游出行规划智能体。用户输入自然语言需求，例如：

```text
我明天从郑州去杭州，玩3天，2个人，酒店300，餐饮120，门票300
```

智能体会完成：

- 提取出发地、目的地、天数、人数和预算信息。
- 在深度思考模式下进行更充分的需求分析和工具选择判断。
- 使用 SQLite 保存历史会话和消息，并基于最近对话历史生成轻量记忆摘要，支持用户连续修改行程。
- 调用天气工具查询目的地或出发地天气。
- 调用交通建议工具生成跨城交通建议。
- 当费用参数明确时调用预算工具。
- 将所有工具结果交给 LLM 汇总，生成最终规划。

本项目提供普通模式和深度思考模式：

- 普通模式：使用 `LLM_MODEL`，适合快速生成结果。本项目配置为 `deepseek-v4-flash`。
- 深度思考模式：使用 `LLM_THINKING_MODEL`，适合实验展示“先分析再行动”的 Agent 思考过程。本项目配置为 `deepseek-v4-pro`。由于 DeepSeek V4 的 API-level thinking 在工具调用场景下要求回传 `reasoning_content`，而当前 LangChain 工具 Agent 不会自动保留该字段，本项目关闭 API-level thinking，使用 Pro 模型和系统提示词实现稳定的深度规划模式。

## 六、工具设计

### 1. 天气查询工具

函数：`get_weather_info`

作用：调用 Open-Meteo API，根据城市名查询实时天气，包括温度、体感温度、天气状况、湿度、风速和气压。

### 2. 预算计算工具

函数：`calculate_trip_budget`

作用：根据城市、天数、人数、住宿、餐饮和门票费用计算总预算。

### 3. 交通建议工具

函数：`get_transport_advice`

作用：根据出发地和目的地给出高铁、飞机、市内交通等建议。

## 七、智能体流程

```text
用户输入
  -> LangChain Agent 接收消息
  -> LLM 理解用户需求
  -> LLM 决定调用哪些工具
  -> 工具返回结构化信息
  -> LLM 综合工具结果
  -> 输出旅行规划
```

## 八、运行结果验证

离线工具链验证命令：

```powershell
C:\Users\BaoXinJie\anaconda3\python.exe run.py --offline-demo -q "我明天从郑州去杭州，玩3天"
```

真实 LLM 调用命令：

```powershell
C:\Users\BaoXinJie\anaconda3\python.exe run.py -q "我明天从郑州去杭州，玩3天，2个人，酒店300，餐饮120，门票300"
```

深度思考模式命令：

```powershell
C:\Users\BaoXinJie\anaconda3\python.exe run.py --thinking -q "我明天从郑州去杭州，玩3天，2个人，酒店300，餐饮120，门票300"
```

真实模式需要在 `.env` 中填写 `LLM_API_KEY`。

## 九、实验总结

通过本实验，可以看到智能体相较普通大模型的关键区别：普通大模型主要负责生成文本，而智能体可以把大模型作为“大脑”，再结合外部工具作为“手脚”，完成更完整的任务闭环。LangChain 降低了工具封装和 Agent 调度的开发难度，适合快速构建具备思考与行动能力的智能应用。
