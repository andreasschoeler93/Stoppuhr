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

export interface NetworkInterfaceInfo {
  name: string;
  state: string;
  mac: string;
  ipv4: string;
  ipv6: string;
}

export interface NetworkStatus {
  default_gateway: string;
  dns_servers: string[];
  interfaces: { [key: string]: NetworkInterfaceInfo };
}

@Injectable({
  providedIn: 'root'
})
export class StatusService {
  private http = inject(HttpClient);

  public systemStatusResource = rxResource({
    loader: () => this.http.get<SystemStatus>('/api/system-status')
  });

  public networkStatusResource = rxResource({
    loader: () => this.http.get<NetworkStatus>('/api/network-status')
  });
}
