// Extracted and strongly typed from docs/strix_prototype.html & docs/sample_result.json

export interface MockCandidate {
  id: number;
  label: string;
  time: number;
  yaw: number;
  pitch: number;
  score: number;
  metrics: {
    sharpness: number;
    illumination: number;
    pose: number;
    occlusion: number;
    resolution: number;
  };
  blur: number;
  dark: number;
  glare: boolean;
  handOcc?: boolean;
  reliability?: 'High' | 'Medium' | 'Low';
  flags?: string[];
  flag_scores?: Record<string, number>;
  secondary_score?: number;
  secondary_warning?: string;
}

export interface MockEvent {
  label: string;
  time: number;
  clock: string;
}

export interface MockCase {
  caseId: string;
  txnId: string;
  title: string;
  atmId: string;
  camera: string;
  location: string;
  dateCreated: string;
  timestamp: string;
  clipsCount: number;
  reviewer: string;
  status: 'In Progress' | 'Pending Review' | 'Verified' | 'Flagged' | 'Archived' | 'Closed' | 'Under Review';
  lastUpdated: string;
  amount: string;
  cardLast4: string;
  matchConfidence: number;
  quality: number;
  conditions: string[];
  sha256: string;
  events: MockEvent[];
  faceProfile: {
    skinTone: number;
    hairStyle: string;
    glasses: boolean;
    cap: boolean;
    beard: boolean;
    seed: number;
  };
  primaryCandidateIdx: number;
  candidates: MockCandidate[];
  notes?: string;
  clipId?: string;
  served_from_demo_pack?: boolean;
}

export interface MockAuditEntry {
  timestamp: string;
  investigator: string;
  action: string;
  refId: string;
  details: string;
  hash: string;
}

export const INITIAL_CASES: MockCase[] = [
            {
                caseId: 'CASE-2026-014',
                txnId: 'TXN-904821',
                title: 'Unauthorized Nighttime Cash Withdrawal',
                atmId: 'ATM-JPR-014',
                camera: 'CAM-01 (Vestibule Overhead)',
                location: 'MI Road Branch, Jaipur',
                dateCreated: '2026-11-26',
                timestamp: '2026-11-26 21:14:24',
                clipsCount: 3,
                reviewer: 'R. Sharma',
                status: 'In Progress',
                lastUpdated: '18 mins ago',
                amount: '₹20,000',
                cardLast4: '4819',
                matchConfidence: 98.4,
                quality: 92,
                conditions: ['Low-Light'],
                sha256: '8f4a2c91d7e0b34f56a12c89e4b7d103a2c4f8e9102b3d4a5c6e7f8091a2b3c4',
                served_from_demo_pack: true,
                events: [
                    { label: 'Card Inserted', time: 4.0, clock: '21:14:02' },
                    { label: 'PIN Verified', time: 11.2, clock: '21:14:09' },
                    { label: 'Cash Dispensed', time: 22.0, clock: '21:14:20' },
                    { label: 'Card Retrieved', time: 28.5, clock: '21:14:26' },
                    { label: 'Session End', time: 33.0, clock: '21:14:31' }
                ],
                faceProfile: { skinTone: 170, hairStyle: 'short', glasses: false, cap: false, beard: true, seed: 14 },
                primaryCandidateIdx: 0,
                candidates: [
                    {
                        id: 1,
                        label: 'Frontal Peak',
                        time: 18.4,
                        yaw: 3,
                        pitch: -2,
                        score: 92,
                        reliability: 'High',
                        flags: ['low_light'],
                        flag_scores: { low_light: 0.88, frontal_alignment: 0.96 },
                        secondary_score: 0.94,
                        metrics: { sharpness: 91, illumination: 88, pose: 96, occlusion: 95, resolution: 90 },
                        blur: 0.3,
                        dark: 0.16,
                        glare: false
                    },
                    {
                        id: 2,
                        label: 'Slight Blur',
                        time: 13.6,
                        yaw: 11,
                        pitch: -4,
                        score: 81,
                        reliability: 'Medium',
                        flags: ['blur', 'low_light'],
                        flag_scores: { blur: 0.74, low_light: 0.82 },
                        secondary_score: 0.85,
                        metrics: { sharpness: 72, illumination: 84, pose: 86, occlusion: 89, resolution: 79 },
                        blur: 1.4,
                        dark: 0.18,
                        glare: false
                    },
                    {
                        id: 3,
                        label: 'Off-Angle 29°',
                        time: 7.5,
                        yaw: 29,
                        pitch: -6,
                        score: 67,
                        reliability: 'Medium',
                        flags: ['partial_face'],
                        flag_scores: { partial_face: 0.65 },
                        secondary_score: 0.86,
                        secondary_warning: 'Enhancement changed the result (>0.15 delta). Treat with caution.',
                        metrics: { sharpness: 76, illumination: 78, pose: 51, occlusion: 81, resolution: 72 },
                        blur: 0.8,
                        dark: 0.20,
                        glare: false
                    },
                    {
                        id: 4,
                        label: 'Hand Occluded',
                        time: 11.5,
                        yaw: 14,
                        pitch: -12,
                        score: 56,
                        reliability: 'Low',
                        flags: ['occlusion', 'hand_covering'],
                        flag_scores: { occlusion: 0.91, hand_covering: 0.84 },
                        secondary_score: 0.58,
                        metrics: { sharpness: 70, illumination: 72, pose: 68, occlusion: 35, resolution: 65 },
                        blur: 0.9,
                        dark: 0.22,
                        glare: false,
                        handOcc: true
                    }
                ]
            },
            {
                caseId: 'CASE-2026-013',
                txnId: 'TXN-904795',
                title: 'Skimmed Card Multiple Dispense Attempt',
                atmId: 'ATM-JPR-003',
                camera: 'CAM-02 (Fascia Pinpad)',
                location: 'Malviya Nagar Sector-4, Jaipur',
                dateCreated: '2026-11-26',
                timestamp: '2026-11-26 19:48:11',
                clipsCount: 2,
                reviewer: 'A. Verma',
                status: 'Pending Review',
                lastUpdated: '2 hours ago',
                amount: '₹15,000',
                cardLast4: '9104',
                matchConfidence: 94.7,
                quality: 84,
                conditions: ['Partial Occlusion'],
                sha256: '3c7e1a05f92d4b8c1e6a7f09d2c3b4a5e6f708192a3b4c5d6e7f8091a2b3c4d5',
                events: [
                    { label: 'Card Inserted', time: 3.5, clock: '19:47:50' },
                    { label: 'PIN Verified', time: 10.5, clock: '19:47:57' },
                    { label: 'Cash Dispensed', time: 21.8, clock: '19:48:08' },
                    { label: 'Card Retrieved', time: 27.6, clock: '19:48:14' },
                    { label: 'Session End', time: 32.4, clock: '19:48:19' }
                ],
                faceProfile: { skinTone: 158, hairStyle: 'short', glasses: true, cap: true, beard: false, seed: 27 },
                primaryCandidateIdx: 0,
                candidates: [
                    { id: 1, label: 'Cap Brim Clear', time: 17.8, yaw: 6, pitch: 2, score: 84, metrics: { sharpness: 88, illumination: 82, pose: 91, occlusion: 73, resolution: 86 }, blur: 0.4, dark: 0.16, glare: false },
                    { id: 2, label: 'Brim Shadow', time: 11.4, yaw: 9, pitch: -15, score: 71, metrics: { sharpness: 80, illumination: 68, pose: 73, occlusion: 57, resolution: 77 }, blur: 0.8, dark: 0.24, glare: false },
                    { id: 3, label: 'Turned 26°', time: 25.0, yaw: 26, pitch: -4, score: 63, metrics: { sharpness: 74, illumination: 75, pose: 54, occlusion: 65, resolution: 70 }, blur: 1.0, dark: 0.18, glare: false },
                    { id: 4, label: 'Lens Glare', time: 6.4, yaw: -16, pitch: 4, score: 52, metrics: { sharpness: 60, illumination: 40, pose: 72, occlusion: 52, resolution: 58 }, blur: 1.2, dark: 0.12, glare: true }
                ]
            },
            {
                caseId: 'CASE-2026-012',
                txnId: 'TXN-904762',
                title: 'Disputed High-Value Dispense Verification',
                atmId: 'ATM-JPR-019',
                camera: 'CAM-01 (Lobby Wide)',
                location: 'Vaishali Nagar Plaza, Jaipur',
                dateCreated: '2026-11-25',
                timestamp: '2026-11-25 16:22:05',
                clipsCount: 2,
                reviewer: 'M. Nair',
                status: 'Verified',
                lastUpdated: 'Yesterday',
                amount: '₹40,000',
                cardLast4: '2271',
                matchConfidence: 99.1,
                quality: 96,
                conditions: ['Backlit'],
                sha256: 'a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90',
                events: [
                    { label: 'Card Inserted', time: 4.5, clock: '16:21:44' },
                    { label: 'PIN Verified', time: 11.5, clock: '16:21:51' },
                    { label: 'Cash Dispensed', time: 23.0, clock: '16:22:03' },
                    { label: 'Card Retrieved', time: 29.0, clock: '16:22:09' },
                    { label: 'Session End', time: 33.5, clock: '16:22:13' }
                ],
                faceProfile: { skinTone: 184, hairStyle: 'long', glasses: false, cap: false, beard: false, seed: 39 },
                primaryCandidateIdx: 0,
                candidates: [
                    { id: 1, label: 'Optimal Frontal', time: 19.2, yaw: 2, pitch: 0, score: 96, metrics: { sharpness: 96, illumination: 94, pose: 98, occlusion: 98, resolution: 95 }, blur: 0.2, dark: 0.06, glare: false },
                    { id: 2, label: 'PIN Look-Up', time: 14.0, yaw: 7, pitch: -4, score: 89, metrics: { sharpness: 90, illumination: 91, pose: 91, occlusion: 88, resolution: 88 }, blur: 0.5, dark: 0.07, glare: false },
                    { id: 3, label: 'Cash Collect', time: 24.4, yaw: -15, pitch: -9, score: 78, metrics: { sharpness: 82, illumination: 87, pose: 74, occlusion: 80, resolution: 78 }, blur: 0.8, dark: 0.08, glare: false },
                    { id: 4, label: 'Door Backlight', time: 31.0, yaw: -28, pitch: 2, score: 58, metrics: { sharpness: 62, illumination: 44, pose: 52, occlusion: 70, resolution: 60 }, blur: 1.2, dark: 0.10, glare: true }
                ]
            },
            {
                caseId: 'CASE-2026-011',
                txnId: 'TXN-904710',
                title: 'Cash-Trapping & Shoulder Surfing Incident',
                atmId: 'ATM-JPR-008',
                camera: 'CAM-03 (Street Vestibule)',
                location: 'Tonk Road Sitapura, Jaipur',
                dateCreated: '2026-11-25',
                timestamp: '2026-11-25 02:39:47',
                clipsCount: 3,
                reviewer: 'R. Sharma',
                status: 'Flagged',
                lastUpdated: '1 day ago',
                amount: '₹25,000',
                cardLast4: '7743',
                matchConfidence: 87.2,
                quality: 64,
                conditions: ['Low-Light', 'Partial Occlusion'],
                sha256: 'f9e8d7c6b5a4938271605f4e3d2c1b0af9e8d7c6b5a4938271605f4e3d2c1b0a',
                events: [
                    { label: 'Card Inserted', time: 3.0, clock: '02:39:25' },
                    { label: 'PIN Verified', time: 12.0, clock: '02:39:34' },
                    { label: 'Cash Dispensed', time: 23.2, clock: '02:39:45' },
                    { label: 'Card Retrieved', time: 29.5, clock: '02:39:51' },
                    { label: 'Session End', time: 34.0, clock: '02:39:56' }
                ],
                faceProfile: { skinTone: 146, hairStyle: 'short', glasses: true, cap: true, beard: true, seed: 52 },
                primaryCandidateIdx: 0,
                candidates: [
                    { id: 1, label: 'Low-Light Best', time: 20.8, yaw: 14, pitch: -8, score: 64, metrics: { sharpness: 66, illumination: 52, pose: 74, occlusion: 61, resolution: 68 }, blur: 1.0, dark: 0.40, glare: false },
                    { id: 2, label: 'Heavy Shadow', time: 15.1, yaw: 20, pitch: -11, score: 56, metrics: { sharpness: 58, illumination: 41, pose: 64, occlusion: 55, resolution: 61 }, blur: 1.3, dark: 0.48, glare: false },
                    { id: 3, label: 'Hand Near Face', time: 12.4, yaw: 17, pitch: -14, score: 49, metrics: { sharpness: 54, illumination: 45, pose: 60, occlusion: 34, resolution: 58 }, blur: 1.2, dark: 0.42, glare: false, handOcc: true },
                    { id: 4, label: 'IR Glare', time: 6.2, yaw: -25, pitch: 5, score: 42, metrics: { sharpness: 47, illumination: 29, pose: 50, occlusion: 48, resolution: 46 }, blur: 1.5, dark: 0.25, glare: true }
                ]
            },
            {
                caseId: 'CASE-2026-010',
                txnId: 'TXN-904688',
                title: 'Off-Angle Cardholder Identity Review',
                atmId: 'ATM-JPR-014',
                camera: 'CAM-01 (Vestibule Overhead)',
                location: 'MI Road Branch, Jaipur',
                dateCreated: '2026-11-24',
                timestamp: '2026-11-24 18:05:19',
                clipsCount: 2,
                reviewer: 'A. Verma',
                status: 'Pending Review',
                lastUpdated: '2 days ago',
                amount: '₹8,000',
                cardLast4: '6302',
                matchConfidence: 92.6,
                quality: 79,
                conditions: ['Off-Angle'],
                sha256: '4b5c6d7e8f90123456789abcdef012344b5c6d7e8f90123456789abcdef01234',
                events: [
                    { label: 'Card Inserted', time: 4.8, clock: '18:05:00' },
                    { label: 'PIN Verified', time: 11.0, clock: '18:05:06' },
                    { label: 'Cash Dispensed', time: 22.5, clock: '18:05:18' },
                    { label: 'Card Retrieved', time: 28.0, clock: '18:05:23' },
                    { label: 'Session End', time: 32.0, clock: '18:05:27' }
                ],
                faceProfile: { skinTone: 178, hairStyle: 'short', glasses: false, cap: false, beard: false, seed: 64 },
                primaryCandidateIdx: 0,
                candidates: [
                    { id: 1, label: '22° Yaw Best', time: 16.5, yaw: 22, pitch: -4, score: 79, metrics: { sharpness: 86, illumination: 84, pose: 68, occlusion: 90, resolution: 81 }, blur: 0.6, dark: 0.12, glare: false },
                    { id: 2, label: '30° Side Pose', time: 12.1, yaw: 30, pitch: -7, score: 70, metrics: { sharpness: 80, illumination: 81, pose: 54, occlusion: 84, resolution: 76 }, blur: 0.8, dark: 0.14, glare: false },
                    { id: 3, label: 'Downward Gaze', time: 24.0, yaw: 18, pitch: -19, score: 62, metrics: { sharpness: 74, illumination: 76, pose: 49, occlusion: 70, resolution: 72 }, blur: 0.9, dark: 0.16, glare: false },
                    { id: 4, label: 'Entry Motion', time: 3.8, yaw: 28, pitch: -2, score: 54, metrics: { sharpness: 51, illumination: 72, pose: 58, occlusion: 71, resolution: 55 }, blur: 1.6, dark: 0.15, glare: false }
                ]
            },
            {
                caseId: 'CASE-2026-009',
                txnId: 'TXN-904599',
                title: 'Fascia Vandalism & Pinpad Inspection',
                atmId: 'ATM-JPR-005',
                camera: 'CAM-02 (Street Exterior)',
                location: 'Mansarovar Shipra Path, Jaipur',
                dateCreated: '2026-11-18',
                timestamp: '2026-11-18 22:51:03',
                clipsCount: 2,
                reviewer: 'M. Nair',
                status: 'Archived',
                lastUpdated: '1 week ago',
                amount: '₹12,000',
                cardLast4: '8934',
                matchConfidence: 96.8,
                quality: 87,
                conditions: ['Low-Light', 'Backlit'],
                sha256: '1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d',
                events: [
                    { label: 'Card Inserted', time: 4.2, clock: '22:50:42' },
                    { label: 'PIN Verified', time: 11.4, clock: '22:50:49' },
                    { label: 'Cash Dispensed', time: 23.0, clock: '22:51:01' },
                    { label: 'Card Retrieved', time: 29.0, clock: '22:51:07' },
                    { label: 'Session End', time: 33.2, clock: '22:51:11' }
                ],
                faceProfile: { skinTone: 180, hairStyle: 'long', glasses: true, cap: false, beard: false, seed: 88 },
                primaryCandidateIdx: 0,
                candidates: [
                    { id: 1, label: 'IR Balanced', time: 19.0, yaw: 5, pitch: -2, score: 87, metrics: { sharpness: 88, illumination: 79, pose: 93, occlusion: 91, resolution: 86 }, blur: 0.4, dark: 0.22, glare: false },
                    { id: 2, label: 'Low Contrast', time: 13.5, yaw: 12, pitch: -6, score: 75, metrics: { sharpness: 76, illumination: 66, pose: 82, occlusion: 84, resolution: 74 }, blur: 0.9, dark: 0.28, glare: false },
                    { id: 3, label: '25° Yaw Turn', time: 8.0, yaw: 25, pitch: -5, score: 67, metrics: { sharpness: 72, illumination: 68, pose: 60, occlusion: 77, resolution: 68 }, blur: 1.0, dark: 0.26, glare: false },
                    { id: 4, label: 'Door Glare', time: 30.8, yaw: -28, pitch: 3, score: 48, metrics: { sharpness: 52, illumination: 36, pose: 50, occlusion: 60, resolution: 51 }, blur: 1.5, dark: 0.20, glare: true }
                ]
            }
        ];

export const INITIAL_AUDIT_LOGS: MockAuditEntry[] = [
            {
                timestamp: '2026-11-26 23:41:12',
                investigator: 'R. Sharma (INV-0412)',
                action: 'Dossier Export',
                refId: 'CASE-2026-014 / TXN-904821',
                details: 'Exported signed forensic dossier (Primary Frame #1, IQA 92/100)',
                hash: '8f4a2c91d7e0b34f56a12c89e4b7d103a2c4f8e9102b3d4a5c6e7f8091a2b3c4'
            },
            {
                timestamp: '2026-11-26 22:18:04',
                investigator: 'A. Verma (INV-0389)',
                action: 'Flag',
                refId: 'CASE-2026-011 / TXN-904710',
                details: 'Escalated case due to low-light partial occlusion and bystander proximity',
                hash: 'f9e8d7c6b5a4938271605f4e3d2c1b0af9e8d7c6b5a4938271605f4e3d2c1b0a'
            },
            {
                timestamp: '2026-11-26 21:55:39',
                investigator: 'R. Sharma (INV-0412)',
                action: 'Frame Override',
                refId: 'CASE-2026-013 / TXN-904795',
                details: 'Confirmed Frame #1 (t=17.8s, IQA 84/100) as primary facial evidence',
                hash: '3c7e1a05f92d4b8c1e6a7f09d2c3b4a5e6f708192a3b4c5d6e7f8091a2b3c4d5'
            },
            {
                timestamp: '2026-11-25 19:02:51',
                investigator: 'M. Nair (INV-0215)',
                action: 'Inspection',
                refId: 'CASE-2026-012 / TXN-904762',
                details: 'Verified cardholder match confidence 99.1% against dispense timestamp',
                hash: 'a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90'
            },
            {
                timestamp: '2026-11-24 18:40:17',
                investigator: 'R. Sharma (INV-0412)',
                action: 'Ingestion',
                refId: 'CASE-2026-010 / TXN-904688',
                details: 'Ingested ATM-JPR-014 CCTV clip + ISO-8583 switch log (864 frames)',
                hash: '4b5c6d7e8f90123456789abcdef012344b5c6d7e8f90123456789abcdef01234'
            }
        ];
