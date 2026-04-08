/**
 * Axion Code — VS Code Extension
 *
 * Main entry point. Activates the sidebar chat panel, registers commands,
 * and spawns the Axion CLI as a background subprocess.
 */

import * as vscode from "vscode";
import { AxionProvider } from "./axionProvider";
import { ChatViewProvider } from "./chatPanel";
import { StatusBarManager } from "./statusBar";

let axionProvider: AxionProvider | undefined;
let statusBar: StatusBarManager | undefined;

export function activate(context: vscode.ExtensionContext) {
  console.log("Axion Code extension activating...");

  // Create the CLI provider (manages the axion subprocess)
  axionProvider = new AxionProvider(context);

  // Create the status bar
  statusBar = new StatusBarManager();
  context.subscriptions.push(statusBar);

  // Register the chat webview provider
  const chatProvider = new ChatViewProvider(
    context.extensionUri,
    axionProvider,
    statusBar
  );
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("axion.chatView", chatProvider)
  );

  // --- Register commands ---

  // Open chat panel
  context.subscriptions.push(
    vscode.commands.registerCommand("axion.openChat", () => {
      vscode.commands.executeCommand("axion.chatView.focus");
    })
  );

  // Ask about selection (right-click menu)
  context.subscriptions.push(
    vscode.commands.registerCommand("axion.askAboutSelection", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) return;
      const selection = editor.document.getText(editor.selection);
      const fileName = editor.document.fileName;
      const prompt = `@${fileName}\n\nAbout this selected code:\n\`\`\`\n${selection}\n\`\`\`\n\nExplain what this code does.`;
      chatProvider.sendMessage(prompt);
    })
  );

  // Review current file
  context.subscriptions.push(
    vscode.commands.registerCommand("axion.reviewFile", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) return;
      const fileName = editor.document.fileName;
      chatProvider.sendMessage(`/review ${fileName}`);
    })
  );

  // Generate tests
  context.subscriptions.push(
    vscode.commands.registerCommand("axion.generateTests", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) return;
      const fileName = editor.document.fileName;
      chatProvider.sendMessage(`/test ${fileName}`);
    })
  );

  // Explain code
  context.subscriptions.push(
    vscode.commands.registerCommand("axion.explainCode", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) return;
      const selection = editor.document.getText(editor.selection);
      chatProvider.sendMessage(
        `Explain this code in detail:\n\`\`\`\n${selection}\n\`\`\``
      );
    })
  );

  // Fix bug in selection
  context.subscriptions.push(
    vscode.commands.registerCommand("axion.fixBug", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) return;
      const selection = editor.document.getText(editor.selection);
      const fileName = editor.document.fileName;
      chatProvider.sendMessage(
        `@${fileName}\n\nFix the bug in this code:\n\`\`\`\n${selection}\n\`\`\``
      );
    })
  );

  // Switch model
  context.subscriptions.push(
    vscode.commands.registerCommand("axion.setModel", async () => {
      const models = [
        "opus",
        "sonnet",
        "haiku",
        "gpt-4o",
        "grok-2",
        "llama3.1",
        "mistral",
      ];
      const picked = await vscode.window.showQuickPick(models, {
        placeHolder: "Select AI model",
      });
      if (picked) {
        axionProvider?.sendCommand(`/model ${picked}`);
        vscode.window.showInformationMessage(`Axion model set to: ${picked}`);
      }
    })
  );

  // Activate license
  context.subscriptions.push(
    vscode.commands.registerCommand("axion.activateLicense", async () => {
      const key = await vscode.window.showInputBox({
        prompt: "Enter your Axion license key",
        placeHolder: "AXION-xxxxx-xxxxx...",
      });
      if (key) {
        axionProvider?.sendCommand(`activate ${key}`);
      }
    })
  );

  // New session
  context.subscriptions.push(
    vscode.commands.registerCommand("axion.newSession", () => {
      axionProvider?.sendCommand("/session new");
    })
  );

  console.log("Axion Code extension activated.");
}

export function deactivate() {
  axionProvider?.dispose();
  statusBar?.dispose();
}
