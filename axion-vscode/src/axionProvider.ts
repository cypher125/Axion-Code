/**
 * AxionProvider — manages the Axion CLI subprocess.
 *
 * Spawns `axion --output-format json` and communicates via stdin/stdout.
 * Parses JSON responses and emits events for the chat panel.
 */

import * as vscode from "vscode";
import { spawn, ChildProcess } from "child_process";
import { EventEmitter } from "events";

export interface AxionResponse {
  message?: string;
  model?: string;
  iterations?: number;
  usage?: {
    input_tokens: number;
    output_tokens: number;
    cache_creation_input_tokens: number;
    cache_read_input_tokens: number;
  };
  estimated_cost?: string;
  tool_uses?: Array<{ name: string; id: string; input: string }>;
  tool_results?: Array<{
    tool_name: string;
    output: string;
    is_error: boolean;
  }>;
  error?: string;
}

export class AxionProvider extends EventEmitter implements vscode.Disposable {
  private process: ChildProcess | undefined;
  private outputBuffer: string = "";
  private ready: boolean = false;

  constructor(private context: vscode.ExtensionContext) {
    super();
  }

  /**
   * Start the Axion CLI subprocess.
   */
  async start(): Promise<void> {
    if (this.process) {
      return;
    }

    const config = vscode.workspace.getConfiguration("axion");
    const cliPath = config.get<string>("cliPath", "axion");
    const model = config.get<string>("model", "sonnet");
    const permMode = config.get<string>("permissionMode", "prompt");
    const budget = config.get<number>("budget", 0);

    const args = [
      "-m",
      model,
      "--output-format",
      "json",
      "--permission-mode",
      permMode,
    ];
    if (budget > 0) {
      args.push("--budget", budget.toString());
    }

    const workspaceFolder =
      vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || process.cwd();

    try {
      this.process = spawn(cliPath, args, {
        cwd: workspaceFolder,
        env: { ...process.env },
        stdio: ["pipe", "pipe", "pipe"],
      });

      this.process.stdout?.on("data", (data: Buffer) => {
        this.handleOutput(data.toString());
      });

      this.process.stderr?.on("data", (data: Buffer) => {
        console.error("[Axion stderr]", data.toString());
      });

      this.process.on("close", (code) => {
        console.log(`Axion process exited with code ${code}`);
        this.ready = false;
        this.process = undefined;
        this.emit("disconnected");
      });

      this.process.on("error", (err) => {
        vscode.window.showErrorMessage(
          `Failed to start Axion: ${err.message}. Make sure 'axion' is installed and in your PATH.`
        );
        this.process = undefined;
      });

      this.ready = true;
      this.emit("connected");
    } catch (err: any) {
      vscode.window.showErrorMessage(`Axion start failed: ${err.message}`);
    }
  }

  /**
   * Send a user message to the Axion CLI.
   */
  async sendMessage(message: string): Promise<void> {
    if (!this.process || !this.ready) {
      await this.start();
    }
    if (this.process?.stdin) {
      this.process.stdin.write(message + "\n");
    }
  }

  /**
   * Send a slash command to the Axion CLI.
   */
  async sendCommand(command: string): Promise<void> {
    return this.sendMessage(command);
  }

  /**
   * Handle output from the Axion subprocess.
   */
  private handleOutput(data: string): void {
    this.outputBuffer += data;

    // Try to parse complete JSON objects from the buffer
    const lines = this.outputBuffer.split("\n");
    this.outputBuffer = lines.pop() || ""; // Keep incomplete line in buffer

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;

      try {
        const response: AxionResponse = JSON.parse(trimmed);
        this.emit("response", response);
      } catch {
        // Not JSON — might be a status message or tool output
        this.emit("text", trimmed);
      }
    }
  }

  /**
   * Check if the Axion CLI is running.
   */
  get isRunning(): boolean {
    return this.ready && this.process !== undefined;
  }

  dispose(): void {
    if (this.process) {
      this.process.kill();
      this.process = undefined;
    }
  }
}
