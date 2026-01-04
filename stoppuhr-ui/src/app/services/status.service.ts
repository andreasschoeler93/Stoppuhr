import {inject, Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {rxResource} from '@angular/core/rxjs-interop';


export interface SystemStatus {
  hostname: string;
  uptime: string;
  cpu_percent: number;
  mem: {
    free: number;
    percent: number;
    total: number;
    used: number;
  };
  disk: {
    free: number;
    percent: number;
    total: number;
    used: number;
  };
  load_avg: number[];
  dienst: string;
}



@Injectable({
  providedIn: 'root'
})
export class StatusService {
  private http = inject(HttpClient);

  public systemStatusResource = rxResource({
    loader: () => this.http.get<SystemStatus>('/api/system-status')
  });
}
