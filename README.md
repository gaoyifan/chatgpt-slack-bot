# ChatGPT Slack Bot

## Overview

The ChatGPT Slack Bot integrates advanced GPT models into Slack, offering functionalities like web browsing, YouTube
video data extraction, and search capabilities with Google and Bing. This integration enhances user interaction within
Slack workspaces by enabling more dynamic and intelligent responses.

## Features

* **LLM Generation**: Generating responses to user messages using large language models.
* **Voice Input**: Transcribing Slack audio clips and generating responses based on the transcriptions.
* **Plugin System**: Easily extend the bot's functionality with [plugins](#plugins).

## Installation

### Prerequisites

- Python 3.11
- Docker (optional for containerized deployment)
- [Just](https://github.com/casey/just) (optional task runner)
- A [Slack App](https://api.slack.com/reference/manifests#creating_apps) configured in your workspace
- [Plugins](#plugins) outlined below

### Setup for Development

1. Clone the repository: `git clone https://github.com/gaoyifan/chatgpt-slack-bot.git`
2. Install dependencies with `pip install -r requirements.txt`.
3. Configure your `.env` file based on the `env.example` template.
4. To run the application, execute `just run`.

### Docker Deployment

Deploy using Docker with the following command:

```shell
docker run -d --env-file=.env gaoyifan/chatgpt-slack-bot
```

## Plugins

| Plugin   | Description                                                                                 | Configurations and References                                                                                                                                                          |
|----------|---------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Browsing | Enables access and information extraction from webpages, PDFs, and GitHub repositories      | [Browse API Serverless](https://github.com/SmartHypercube/browse-api-serverless)                                                                                                       |
| Search   | Conducts searches through Google and Bing                                                   | [Google Custom Search API](https://developers.google.com/custom-search/v1/introduction), [Bing Search API](https://docs.microsoft.com/en-us/bing/search-apis/bing-search-v7-reference) |
| YouTube  | Extracts video titles, channel information, descriptions, and subtitles from YouTube videos |                                                                                                                                                                                        |

## Environment Variables

| Environment Variable              | Description                                                   | Default Value        |
|-----------------------------------|---------------------------------------------------------------|----------------------|
| `SLACK_BOT_TOKEN`                 | OAuth Access Token for your Slack bot, starting with `xoxb-`. | Required             |
| `SLACK_APP_TOKEN`                 | App-level token for your Slack bot, starting with `xapp-`.    | Required             |
| `OPENAI_API_KEY`                  | API key for accessing OpenAI services.                        | Required             |
| `OPENAI_MODEL`                    | Identifier for the OpenAI model to use.                       | `gpt-4-1106-preview` |
| `LOG_LEVEL`                       | Logging level for application output.                         | `INFO`               |
| `DB_PATH`                         | Path to the SQLite database file.                             | `db.sqlite`          |
| `BROWSER_TEXT_API_URL`            | API URL for browsing text functionality.                      | Required             |
| `GITHUB_API_URL`                  | API URL for extracting metadata from GitHub repositories.     | Required             |
| `PDF_API_URL`                     | API URL for extracting text from PDF files.                   | Required             |
| `GOOGLE_SEARCH_KEY`               | API key for Google Custom Search services.                    | Required             |
| `GOOGLE_SEARCH_CX`                | Custom Search Engine ID for Google Custom Search.             | Required             |
| `BING_SEARCH_V7_SUBSCRIPTION_KEY` | Subscription key for Bing Search V7.                          | Required             |
| `BING_SEARCH_V7_ENDPOINT`         | Endpoint URL for Bing Search V7 API.                          | Required             |

## TODO

- [ ] Develop an asynchronous wrapper for yt-dlp.
- [ ] Implement a code interpreter.

## Contributing

We warmly welcome contributions. If you have improvements or fixes, please feel free to submit pull requests.

## Acknowledgements

Special thanks to these projects and contributors for their significant impact on the development of our ChatGPT Slack
Bot:

1. **[chatgpt-telegram-bot](https://github.com/zzh1996/chatgpt-telegram-bot)** by [zzh1996](https://github.com/zzh1996):
   This project was key in shaping our bot's architecture and functionality, offering valuable insights into chatbot
   integration in messaging platforms.

2. **[browse-api-serverless](https://github.com/SmartHypercube/browse-api-serverless)**
   by [SmartHypercube](https://github.com/SmartHypercube): Provided an efficient, scalable solution for web browsing
   functionalities, a core feature of our bot.

3. **[autogen](https://github.com/microsoft/autogen)**: Our gratitude to the Autogen library for simplifying the
   generation and handling of tool calls, thereby significantly reducing development complexity and time.

## License

[MIT License](LICENSE)
