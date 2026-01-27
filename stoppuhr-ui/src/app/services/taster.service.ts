import {inject, Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {rxResource} from '@angular/core/rxjs-interop';

export interface Taster {
  name: string;
  mac: string;
  ts: number;
  stopwatch_ms: number | null;
}

export interface MappingResponse {
  mapping: { [lane: string]: Taster | null }; // Lane number -> MAC address
  unmapped_taster: Taster[];
  starter: Taster | null;
}

export interface PostTasterResponse {
  ok: boolean;
  taster?: Taster;
  error?: string;
}

@Injectable({
  providedIn: 'root'
})
export class TasterService {
  private http = inject(HttpClient);

  /**
   * Fetches the mapping state, including lane assignments and unmapped tasters.
   */
  public mappingResource = rxResource({
    loader: () => this.http.get<MappingResponse>('/api/mapping')
  });

  /**
   * Registers or updates a taster
   */
  registerTaster(taster: Partial<Taster>) {
    return this.http.post<PostTasterResponse>('/api/taster', taster);
  }

  /**
   * Reloads the mapping and unmapped tasters
   */
  reload() {
    this.mappingResource.reload();
  }

  /**
   * Assigns a specific Taster (MAC) to a Lane
   */
  assignTasterToLane(mac: string, lane: string) {
    return this.http.post<PostTasterResponse>('/api/assign', {mac, lane});
  }

  /**
   * Removes any Taster assignment from a specific Lane
   */
  unassignTaster(lane: string) {
    // Assuming the API expects an empty mac or has a dedicated delete/unassign route
    return this.http.post<PostTasterResponse>('/api/unassign', {lane});
  }
}
