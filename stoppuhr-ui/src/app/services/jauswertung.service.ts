import {inject, Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {rxResource} from '@angular/core/rxjs-interop';

export interface JAuswertungStartCards {
  ok: boolean;
  row_count: number;
  max_lane: number;
  runs: string[];
  source_url: string;
  last_fetch_ts: number;
  error?: string;
}

@Injectable({
  providedIn: 'root'
})
export class JAuswertungService {
  private http = inject(HttpClient);

  public startkartenResource = rxResource({
    loader: () => this.http.get<JAuswertungStartCards>('/api/startcards')
  });

  reload() {
    this.startkartenResource.reload();
  }
}
