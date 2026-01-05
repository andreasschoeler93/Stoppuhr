import {ComponentFixture, TestBed} from '@angular/core/testing';

import {NetzwerkComponent} from './netzwerk.component';

describe('NetzwerkComponent', () => {
  let component: NetzwerkComponent;
  let fixture: ComponentFixture<NetzwerkComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [NetzwerkComponent]
    })
      .compileComponents();

    fixture = TestBed.createComponent(NetzwerkComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
