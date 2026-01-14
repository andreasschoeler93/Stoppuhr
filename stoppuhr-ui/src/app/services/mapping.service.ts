import {inject, Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {rxResource} from '@angular/core/rxjs-interop';


export interface Trigger {
  name: string;
  mac: string;
  ts: number;
  stopwatch_ms: number | null;
}

export interface Assignments {
  mapping: Record<string, any>;
  last_update_ts: number | null;
}

@Injectable({
  providedIn: 'root'
})
export class MappingService {
  private http = inject(HttpClient);

  public assignmentsResource = rxResource({
    loader: () => this.http.get<Assignments>('/api/assignments')
  });

  saveAssignments(mapping: Record<string, any>) {
    return this.http.post<Assignments>('/api/assignments', {mapping});
  }
}
