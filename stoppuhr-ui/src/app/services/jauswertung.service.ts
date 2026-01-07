import {inject, Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {rxResource} from '@angular/core/rxjs-interop';

export interface JAuswertungStartCards {
  ok: boolean;
  row_count: number;
  max_lane: number;
  runs: string[];
  rows: string[];
  source_url: string;
  last_fetch_ts: number;
  error?: string;
  startcards_per_run: { [run: string]: StartCard[] };
}

export interface StartCard {
  Altersklasse: string;
  Bahn: string;
  Bemerkung: string;
  Disziplin: string;
  Geschlecht: string;
  Gliederung: string;
  Jahrgang: string;
  Lauf: string;
  Nachname: string;
  Name: string;
  'Q-Gld': string;
  Runde: string;
  Startnummer: string;
  Vorname: string;
  Wettkampf: string;
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
