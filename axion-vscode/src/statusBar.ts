/**
 * StatusBarManager — shows token count and cost in VS Code's status bar.
 */

import * as vscode from "vscode";

export class StatusBarManager implements vscode.Disposable {
  private statusItem: vscode.StatusBarItem;
  private totalTokens: number = 0;
  private totalCost: string = "$0.0000";

  constructor() {
    this.statusItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Right,
      100
    );
    this.statusItem.text = "$(comment-discussion) Axion";
    this.statusItem.tooltip = "Axion Code — Click to open chat";
    this.statusItem.command = "axion.openChat";
    this.statusItem.show();
  }

  update(tokens: number, cost: string): void {
    this.totalTokens += tokens;
    this.totalCost = cost || this.totalCost;
    this.statusItem.text = `$(comment-discussion) Axion | ${this.totalTokens.toLocaleString()} tokens | ${this.totalCost}`;
  }

  dispose(): void {
    this.statusItem.dispose();
  }
}
