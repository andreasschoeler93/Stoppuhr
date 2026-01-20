import {Component, computed, inject, signal} from '@angular/core';
import {DragDropModule} from '@angular/cdk/drag-drop';
import {CommonModule} from '@angular/common';
import {MatCardModule} from '@angular/material/card';
import {MatTableModule} from '@angular/material/table';
import {FormsModule} from '@angular/forms';
import {MatInputModule} from '@angular/material/input';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatButtonModule} from '@angular/material/button';
import {MatSelectModule} from '@angular/material/select';
import {StatusService} from '../../services/status.service';
import {JAuswertungService} from '../../services/jauswertung.service';
import {TasterService} from '../../services/taster.service';
import {TasterCardComponent} from '../../component/taster-card/taster-card.component';

@Component({
  selector: 'app-stoppuhr',
  standalone: true,
  imports: [CommonModule,
    FormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatSelectModule,
    MatTableModule,
    DragDropModule, TasterCardComponent,
  ],
  templateUrl: './stoppuhr.component.html',
  styleUrls: ['./stoppuhr.component.scss'],
})
export class StoppuhrComponent {

  private statusService = inject(StatusService);
  protected jauswertungService = inject(JAuswertungService);
  protected tasterService = inject(TasterService)
  public runs: string[] = [];

  /**
   * Helper to look up taster info + vitals by MAC
   */
  allTastersMap = computed(() => {
    const data = this.tasterService.mappingResource.value();
    // Assuming statusService has a resource for vitals mapping mac -> vitals
    const vitalsData = this.statusService.systemStatusResource.value(); // Adjust if vitals are elsewhere

    const tasterMap = new Map<string, any>();
    if (!data) return tasterMap;
    if (data.mapping) {
      Object.entries(data.mapping).forEach(([lane, taster]) => {
        if (taster && !tasterMap.has(taster.mac)) {
          tasterMap.set(taster.mac, taster);
        }
      });
    }

    return tasterMap;
    /*    console.log("!!!!!!");
        console.log(data);
        // Build map from unmapped list (primary source for taster metadata)
        data.unmapped_taster.forEach(t => {
          // In a real scenario, you'd merge vitals from your vitals endpoint here
          tasterMap.set(t.mac, {...t, vitals: null});
        });
        console.log("???????");
        console.log(tasterMap);
        return tasterMap;*/
  });

  fullUrl = computed(() => {
    const s = this.statusService.settingsResource.value();
    if (!s || !s.startcards_base_url) return 'URL nicht konfiguriert';
    return s.startcards_base_url + (s.startcards_suffix || '');
  });
  statusText = computed(() => {
    const resource = this.jauswertungService.startkartenResource;

    if (resource.isLoading()) return 'Lade Startkarten...';
    if (resource.error()) {
      // You can check the error object here if needed
      return 'Fehler: Konnte Startkarten nicht laden.';
    }
    if (resource.value()) {
      return `Erfolgreich geladen (${new Date().toLocaleTimeString()})`;
    }
    return 'Status: bereit.';
  });


  selectedLauf = signal<string | null>(null);
  selectedTasterForAssignment = signal<string | null>(null);

  // Filter the rows based on the selected run
  filteredBahnen = computed(() => {
    const data = this.jauswertungService.startkartenResource.value();
    const mappingData = this.tasterService.mappingResource.value(); // Get the current mapping
    const lauf = this.selectedLauf();

    if (!data || !data.rows || !lauf) return [];

    const runRows = data.rows.filter((row: any) => String(row.Lauf) === String(lauf));
    const maxLane = data.max_lane || 0;
    const result = [];

    for (let b = 1; b <= maxLane; b++) {
      const starter = runRows.find((r: any) => Number(r.Bahn) === b);
      // Find if there is a taster assigned to this lane MAC address
      const assignedMac = mappingData?.mapping?.[String(b)];

      // @ts-ignore
      //TdDo: What is this?
      const baseInfo = starter ? {...starter} : {
        Bahn: b,
        Vorname: '-',
        Nachname: '',
        Startnummer: '-',
        Disziplin: '-'
      };

      // Attach the assigned MAC to the row object for the template
      result.push({
        ...baseInfo,
        assignedMac: assignedMac || null
      });
    }

    return result;
  });

  laufOptions = computed(() => {
    const data = this.jauswertungService.startkartenResource.value();
    if (!data || !data.runs) return [];
    return data.runs.map(run => ({
      value: run,
      label: `Lauf ${run}`
    }));
  });

  maxBahnenText = computed(() => {
    const data = this.jauswertungService.startkartenResource.value();
    if (!data || data.max_lane === undefined) {
      return 'Max. Bahnen: –';
    }
    return `Max. Bahnen: ${data.max_lane}`;
  });

  displayedColumns = ['bahn', 'name', 'startnr', 'disziplin', 'taster'];


  loadStartkarten() {
    this.jauswertungService.reload();

  }

  assignTaster(mac: string, lane: string) {
    this.tasterService.assignTasterToLane(mac, lane).subscribe({
      next: () => {
        this.tasterService.reload();
      },
      error: (err) => console.error('Assignment failed', err)
    });
  }

  removeTasterFromLane(lane: string) {
    this.tasterService.unassignTaster(lane).subscribe({
      next: () => this.tasterService.reload(),
      error: (err) => console.error('Unassignment failed', err)
    });
  }


}
