# Pixel Viewer Wireframe

This document describes the current and intended wireframe for the ER hospital pixel viewer.

## Main Layout

The screen is divided into two primary zones.

### Left: Main Hospital Scene

This is the dominant area of the screen.

It contains:
- waiting area
- ER workup beds
- observation area
- consult hall
- specialty wing

The scene should remain the visual focus.

### Right: Context Column

This column contains supporting information.

Current panels:
- `Overview`
- `Patients`
- `Case Detail`
- `Conversation`

## Scene Zones

### Waiting

Purpose:
- patients arrive here first
- idle queue patients remain visible here

Expected entities:
- waiting patients
- reception staff
- chairs / side tables

### ER Beds

Purpose:
- active ER questioning, assessment, and workup

Expected entities:
- patient in active workup
- ER doctor
- imaging/test markers nearby

### Observation

Purpose:
- patients placed under observation or reassessment

Expected entities:
- observation patient
- nurse / support staff

### Consult Hall

Purpose:
- handoff staging area
- specialty review flow

Expected entities:
- summoned specialty doctor
- patient moved for consult
- consult-room furniture or booth markers

### Specialty Wing

Purpose:
- idle specialty doctors live here
- this should read like office pods, not just a vertical list

Expected entities:
- specialty doctors by department
- desks / chairs / office pod furniture

## Right Panel Intent

### Overview

Shows compact run status:
- current minute
- completed count
- waiting count
- active resource count
- active ER focus
- acuity legend

### Patients

Shows current patient list:
- case id
- triage
- zone
- alerts

This is also a selection surface.

### Case Detail

Shows data for the selected case:
- triage and risk
- pending results count
- previous questions and answers
- requested tests
- objective findings

This panel is meant to act like a compact chart view.

### Conversation

Shows:
- current minute conversation
- selected case conversation
- ER and specialty conversation blocks when available

This panel should support:
- temporal understanding
- selected-case review

## Current Interaction Model

Selection can happen by:
- clicking a patient sprite in the scene
- clicking a patient row in the `Patients` panel

The selected case drives:
- `Case Detail`
- selected-case conversation section

## Current Runtime Notes

The scene is backed by:
- static hospital background PNG
- sprite atlas for agents and furniture
- live entity overlays

Movement is currently:
- interpolation between snapshots

Not yet full pathfinding or tile walking.

## Intended Visual Hierarchy

1. Hospital scene first
2. Active ER/specialty interactions second
3. Right-side context third

This should avoid the “dashboard first, scene second” feeling.

## Recommended Next Wireframe Improvements

- make specialty wing more pod-like and less linear
- give consult hall stronger room identity
- visually emphasize selected case in both scene and side panels
- introduce a bottom event/timeline strip when needed
