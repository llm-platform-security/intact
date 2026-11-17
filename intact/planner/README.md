# Planner

This package holds Intact's planner, Vanilla, and functionality extraction. All three call a model through OpenRouter and read your key from `OPENROUTER_API_KEY`. The model is `openai/gpt-6-luna` unless you pass `--model`.


## Intact's planner

`plan_iterative` splits the page's markup into chunks of about 1,500 characters and asks the model which chunk the task needs. It then walks that chunk one element per call, in page order, and continues to the end of a form if the chunk ends inside one. Each call shows the task, the element's own markup, and a log of the operations decided so far. The model answers whether the task needs the element and, if so, with which operation (`click`, `type`, `select`, or `none` when the task needs only its content) and which value. The model never names an element. The code links each decision to the element that the call showed.

## Vanilla

`plan_collective` shows the model the whole page in one call, with each line tagged by its element's id (`[bni=N]`). The model returns the ordered steps and cites each element by its id.

## Functionality extraction

`classify_functionalities` shows the model the page and asks for five things that real users would ask an agent to do on it. Each task has a short name, the user's request, and its interaction type: `single action`, `several actions`, or `read then act`.

## Output

| Command | Writes |
|---|---|
| `classify_functionalities <page>` | `functionalities/<page>.json`: the page, its URL, the model, the five tasks, and the usage |
| `plan_iterative <page>` | `plans/iterative/<page>.json`: one plan for each task in `functionalities/<page>.json` |
| `plan_collective <page>` | `plans/collective/<page>.json`: one plan for each task in `functionalities/<page>.json` |

A plan holds the task and its steps. Each step has the element's `bni`, the `operation`, the `value`, the element's `markup`, and `acts_on`, the element that the step acts on. A plan also holds the trace of every model call (the request, the raw reply, and how the code parsed it) and the usage (calls, tokens, cost, and seconds). Intact's plans also record the walk: how many chunks the page has, how many the model found relevant, which one it chose, and how many elements it saw.

Running a planner again keeps the plans that succeeded and plans the rest. A rerun with another `--model` stops before any model call, because the folder already holds another model's plans; give it another `--out`.
