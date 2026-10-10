import { HttpClient, HttpEvent } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { AuthService } from '../auth/auth.service';
import { AppConfigService } from '../config/app-config.service';
import { Attachment, Claim, ClaimSummary, Receipt, ReceiptUpdate } from '../models/models';

@Injectable({ providedIn: 'root' })
export class ClaimsApi {
  private readonly http = inject(HttpClient);
  private readonly config = inject(AppConfigService);
  private readonly auth = inject(AuthService);

  private url(path = ''): string {
    return this.config.api(`/claims${path}`);
  }

  list(): Observable<ClaimSummary[]> {
    return this.http.get<ClaimSummary[]>(this.url());
  }

  create(body: { title?: string; purpose?: string } = {}): Observable<Claim> {
    return this.http.post<Claim>(this.url(), body);
  }

  get(id: string): Observable<Claim> {
    return this.http.get<Claim>(this.url(`/${id}`));
  }

  update(id: string, body: { title?: string; purpose?: string }): Observable<Claim> {
    return this.http.patch<Claim>(this.url(`/${id}`), body);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(this.url(`/${id}`));
  }

  upload(id: string, files: File[]): Observable<HttpEvent<Receipt[]>> {
    const form = new FormData();
    files.forEach((file) => form.append('files', file, file.name));
    return this.http.post<Receipt[]>(this.url(`/${id}/receipts`), form, {
      reportProgress: true,
      observe: 'events',
    });
  }

  updateReceipt(id: string, receiptId: string, body: ReceiptUpdate): Observable<Claim> {
    return this.http.patch<Claim>(this.url(`/${id}/receipts/${receiptId}`), body);
  }

  retryReceipt(id: string, receiptId: string): Observable<Claim> {
    return this.http.post<Claim>(this.url(`/${id}/receipts/${receiptId}/retry`), {});
  }

  deleteReceipt(id: string, receiptId: string): Observable<Claim> {
    return this.http.delete<Claim>(this.url(`/${id}/receipts/${receiptId}`));
  }

  answer(id: string, questionId: string, answer: unknown): Observable<Claim> {
    return this.http.post<Claim>(this.url(`/${id}/questions/${questionId}/answer`), { answer });
  }

  chat(id: string, message: string): Observable<Claim> {
    return this.http.post<Claim>(this.url(`/${id}/chat`), { message });
  }

  submit(id: string): Observable<Claim> {
    return this.http.post<Claim>(this.url(`/${id}/submit`), {});
  }

  reopen(id: string): Observable<Claim> {
    return this.http.post<Claim>(this.url(`/${id}/reopen`), {});
  }

  /**
   * URLs used directly by <img>, <iframe> and download links (token in the query string).
   * `approval` goes through the approver-scoped endpoint; `download` forces a file download.
   */
  fileUrl(id: string, receiptId: string, opts: { download?: boolean; approval?: boolean } = {}): string {
    const base = opts.approval ? this.config.api(`/approvals/${id}`) : this.url(`/${id}`);
    const download = opts.download ? '&download=true' : '';
    return `${base}/receipts/${receiptId}/file?access_token=${this.auth.token()}${download}`;
  }

  /** View/download links for a receipt's original document. */
  attachment(receipt: Receipt, subtitle: string, approval = false): Attachment {
    return {
      id: receipt.id,
      name: receipt.file_name,
      mimeType: receipt.mime_type,
      sizeBytes: receipt.size_bytes,
      subtitle,
      viewUrl: this.fileUrl(receipt.claim_id, receipt.id, { approval }),
      downloadUrl: this.fileUrl(receipt.claim_id, receipt.id, { approval, download: true }),
    };
  }

  attachmentsZipUrl(id: string, approval = false): string {
    const base = approval ? this.config.api(`/approvals/${id}`) : this.url(`/${id}`);
    return `${base}/attachments.zip?access_token=${this.auth.token()}`;
  }

  exportUrl(id: string): string {
    return `${this.url(`/${id}/export`)}?access_token=${this.auth.token()}`;
  }
}
