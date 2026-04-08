/**
 * ChatViewProvider — webview panel for the Axion chat interface.
 *
 * Renders messages, tool use/results, and handles user input.
 * Communicates with the AxionProvider subprocess.
 */

import * as vscode from "vscode";
import { AxionProvider, AxionResponse } from "./axionProvider";
import { StatusBarManager } from "./statusBar";

export class ChatViewProvider implements vscode.WebviewViewProvider {
  private view?: vscode.WebviewView;
  private messageHistory: Array<{
    role: string;
    content: string;
    timestamp: number;
  }> = [];

  constructor(
    private extensionUri: vscode.Uri,
    private axionProvider: AxionProvider,
    private statusBar: StatusBarManager
  ) {
    // Listen for responses from the Axion CLI
    this.axionProvider.on("response", (response: AxionResponse) => {
      this.handleResponse(response);
    });
    this.axionProvider.on("text", (text: string) => {
      this.addMessage("system", text);
    });
  }

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ): void {
    this.view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this.extensionUri],
    };

    webviewView.webview.html = this.getHtml();

    // Handle messages from the webview
    webviewView.webview.onDidReceiveMessage(async (message) => {
      switch (message.type) {
        case "send":
          await this.handleUserMessage(message.text);
          break;
        case "command":
          await this.axionProvider.sendCommand(message.command);
          break;
      }
    });
  }

  /**
   * Send a message from outside the webview (e.g., from a command).
   */
  async sendMessage(text: string): Promise<void> {
    await this.handleUserMessage(text);
  }

  private async handleUserMessage(text: string): Promise<void> {
    // Show user message in chat
    this.addMessage("user", text);

    // Show thinking indicator
    this.view?.webview.postMessage({
      type: "thinking",
      active: true,
    });

    // Send to Axion CLI
    await this.axionProvider.sendMessage(text);
  }

  private handleResponse(response: AxionResponse): void {
    // Stop thinking indicator
    this.view?.webview.postMessage({
      type: "thinking",
      active: false,
    });

    // Show tool uses
    if (response.tool_uses) {
      for (const tool of response.tool_uses) {
        this.view?.webview.postMessage({
          type: "tool_use",
          name: tool.name,
          input: tool.input,
        });
      }
    }

    // Show tool results
    if (response.tool_results) {
      for (const result of response.tool_results) {
        this.view?.webview.postMessage({
          type: "tool_result",
          name: result.tool_name,
          output: result.output,
          isError: result.is_error,
        });
      }
    }

    // Show assistant message
    if (response.message) {
      this.addMessage("assistant", response.message);
    }

    // Show error
    if (response.error) {
      this.addMessage("error", response.error);
    }

    // Update status bar
    if (response.usage) {
      const totalTokens =
        response.usage.input_tokens + response.usage.output_tokens;
      this.statusBar.update(totalTokens, response.estimated_cost || "");
    }
  }

  private addMessage(role: string, content: string): void {
    this.messageHistory.push({
      role,
      content,
      timestamp: Date.now(),
    });

    this.view?.webview.postMessage({
      type: "message",
      role,
      content,
    });
  }

  private getHtml(): string {
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Axion Code</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }

    body {
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
      color: var(--vscode-foreground);
      background: var(--vscode-sideBar-background);
      display: flex;
      flex-direction: column;
      height: 100vh;
    }

    /* Header */
    .header {
      padding: 12px 16px;
      border-bottom: 1px solid var(--vscode-panel-border);
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .header .logo {
      color: #00d4aa;
      font-weight: bold;
      font-size: 14px;
    }
    .header .model {
      color: var(--vscode-descriptionForeground);
      font-size: 12px;
    }

    /* Messages area */
    .messages {
      flex: 1;
      overflow-y: auto;
      padding: 12px;
    }

    .message {
      margin-bottom: 16px;
      padding: 10px 14px;
      border-radius: 8px;
      max-width: 95%;
    }
    .message.user {
      background: var(--vscode-input-background);
      border: 1px solid var(--vscode-input-border);
      margin-left: auto;
    }
    .message.assistant {
      background: var(--vscode-editor-background);
      border: 1px solid var(--vscode-panel-border);
    }
    .message.error {
      background: rgba(255, 107, 107, 0.1);
      border: 1px solid #ff6b6b;
      color: #ff6b6b;
    }
    .message.system {
      color: var(--vscode-descriptionForeground);
      font-size: 12px;
      font-style: italic;
    }

    .message .role {
      font-size: 11px;
      font-weight: bold;
      margin-bottom: 4px;
      text-transform: uppercase;
    }
    .message.user .role { color: #00d4aa; }
    .message.assistant .role { color: #64ffda; }

    .message pre {
      background: var(--vscode-textCodeBlock-background);
      padding: 8px;
      border-radius: 4px;
      overflow-x: auto;
      margin: 8px 0;
    }
    .message code {
      font-family: var(--vscode-editor-font-family);
      font-size: var(--vscode-editor-font-size);
    }

    /* Tool panels */
    .tool-use, .tool-result {
      margin: 8px 0;
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 12px;
    }
    .tool-use {
      border-left: 3px solid #00d4aa;
      background: rgba(0, 212, 170, 0.05);
    }
    .tool-result {
      border-left: 3px solid #64ffda;
      background: rgba(100, 255, 218, 0.05);
    }
    .tool-result.error {
      border-left-color: #ff6b6b;
      background: rgba(255, 107, 107, 0.05);
    }
    .tool-name {
      font-weight: bold;
      color: #00d4aa;
    }

    /* Thinking indicator */
    .thinking {
      padding: 8px 16px;
      color: var(--vscode-descriptionForeground);
      font-style: italic;
      display: none;
    }
    .thinking.active { display: block; }

    /* Input area */
    .input-area {
      padding: 12px;
      border-top: 1px solid var(--vscode-panel-border);
    }
    .input-area textarea {
      width: 100%;
      min-height: 60px;
      max-height: 200px;
      padding: 10px;
      border: 1px solid var(--vscode-input-border);
      background: var(--vscode-input-background);
      color: var(--vscode-input-foreground);
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
      border-radius: 6px;
      resize: vertical;
      outline: none;
    }
    .input-area textarea:focus {
      border-color: #00d4aa;
    }
    .input-area .hint {
      font-size: 11px;
      color: var(--vscode-descriptionForeground);
      margin-top: 4px;
    }
    .input-area .hint kbd {
      background: var(--vscode-keybindingLabel-background);
      border: 1px solid var(--vscode-keybindingLabel-border);
      border-radius: 3px;
      padding: 1px 4px;
      font-size: 10px;
    }
  </style>
</head>
<body>
  <div class="header">
    <span class="logo">◆ AXION</span>
    <span class="model" id="model-display">connecting...</span>
  </div>

  <div class="messages" id="messages"></div>

  <div class="thinking" id="thinking">Thinking...</div>

  <div class="input-area">
    <textarea
      id="input"
      placeholder="Ask Axion anything... (use @file to reference files)"
      rows="3"
    ></textarea>
    <div class="hint">
      <kbd>Enter</kbd> to send · <kbd>Shift+Enter</kbd> for newline · Type <kbd>@</kbd> to reference files
    </div>
  </div>

  <script>
    const vscode = acquireVsCodeApi();
    const messagesEl = document.getElementById('messages');
    const inputEl = document.getElementById('input');
    const thinkingEl = document.getElementById('thinking');
    const modelEl = document.getElementById('model-display');

    // Send message on Enter
    inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const text = inputEl.value.trim();
        if (text) {
          vscode.postMessage({ type: 'send', text });
          inputEl.value = '';
          inputEl.style.height = 'auto';
        }
      }
    });

    // Auto-resize textarea
    inputEl.addEventListener('input', () => {
      inputEl.style.height = 'auto';
      inputEl.style.height = inputEl.scrollHeight + 'px';
    });

    // Handle messages from extension
    window.addEventListener('message', (event) => {
      const msg = event.data;

      switch (msg.type) {
        case 'message':
          addMessage(msg.role, msg.content);
          break;
        case 'thinking':
          thinkingEl.classList.toggle('active', msg.active);
          break;
        case 'tool_use':
          addToolUse(msg.name, msg.input);
          break;
        case 'tool_result':
          addToolResult(msg.name, msg.output, msg.isError);
          break;
        case 'model':
          modelEl.textContent = msg.name;
          break;
      }
    });

    function addMessage(role, content) {
      const div = document.createElement('div');
      div.className = 'message ' + role;

      const roleLabel = document.createElement('div');
      roleLabel.className = 'role';
      roleLabel.textContent = role === 'user' ? 'You' : role === 'assistant' ? 'Axion' : role;
      div.appendChild(roleLabel);

      const body = document.createElement('div');
      // Simple markdown-ish rendering
      body.innerHTML = renderMarkdown(content);
      div.appendChild(body);

      messagesEl.appendChild(div);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function addToolUse(name, input) {
      const div = document.createElement('div');
      div.className = 'tool-use';
      div.innerHTML = '<span class="tool-name">⚡ ' + escapeHtml(name) + '</span><br><small>' + escapeHtml(input).substring(0, 200) + '</small>';
      messagesEl.appendChild(div);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function addToolResult(name, output, isError) {
      const div = document.createElement('div');
      div.className = 'tool-result' + (isError ? ' error' : '');
      const icon = isError ? '✗' : '✓';
      div.innerHTML = '<span class="tool-name">' + icon + ' ' + escapeHtml(name) + '</span><br><small>' + escapeHtml(output).substring(0, 500) + '</small>';
      messagesEl.appendChild(div);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function renderMarkdown(text) {
      // Basic markdown rendering
      let html = escapeHtml(text);
      // Code blocks
      html = html.replace(/\`\`\`([\\s\\S]*?)\`\`\`/g, '<pre><code>$1</code></pre>');
      // Inline code
      html = html.replace(/\`([^\`]+)\`/g, '<code>$1</code>');
      // Bold
      html = html.replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
      // Newlines
      html = html.replace(/\\n/g, '<br>');
      return html;
    }

    function escapeHtml(text) {
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }

    // Focus input on load
    inputEl.focus();
  </script>
</body>
</html>`;
  }
}
