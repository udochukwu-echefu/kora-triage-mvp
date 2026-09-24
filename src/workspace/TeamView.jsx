import { useState } from "react";
import { ChevronRight, Search, Users } from "lucide-react";
import { cn } from "../lib/utils";
import { initialsOf } from "../lib/tickets";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";

const AVAILABILITY = ["Online", "Busy", "Away", "Offline"];
const TONES = ["gold", "teal", "blue", "cream"];

export default function TeamView({ tickets, members, loading, currentUser, onFilterQueue, onSetAvailability }) {
  const [query, setQuery] = useState("");
  const [availability, setAvailability] = useState("All");
  const isManager = ["support_manager", "admin"].includes(currentUser?.role);
  const openTickets = tickets.filter((ticket) => ticket.lifecycle?.state !== "resolved");
  const rows = members.map((member, index) => {
    const assigned = openTickets.filter((ticket) => ticket.lifecycle?.assigned_to === member.name || ticket.assignee === member.name).length;
    return { ...member, assigned, overloaded: assigned > member.capacity, tone: TONES[index % TONES.length] };
  });
  const assignedTotal = rows.reduce((total, member) => total + member.assigned, 0);
  const totalCapacity = rows.reduce((total, member) => total + member.capacity, 0);
  const unassigned = openTickets.filter((ticket) => !ticket.lifecycle?.assigned_to && !ticket.assignee).length;
  const filters = ["All", ...AVAILABILITY];
  const normalizedQuery = query.trim().toLowerCase();
  const visibleMembers = rows.filter((member) => {
    const matchesStatus = availability === "All" || member.availability === availability;
    const matchesQuery = !normalizedQuery || [member.name, member.role, ...member.teams].join(" ").toLowerCase().includes(normalizedQuery);
    return matchesStatus && matchesQuery;
  });
  const filterCount = (filter) => filter === "All" ? rows.length : rows.filter((member) => member.availability === filter).length;
  const clearFilters = () => { setQuery(""); setAvailability("All"); };

  if (!loading && !members.length) {
    return <div className="view-padding team-page"><section className="team-directory"><div className="p-10 text-center"><Users className="mx-auto size-6 text-ink-faint" /><strong className="mt-3 block">No team roster yet</strong><p className="mt-2 text-sm text-ink-muted">Add teammates to the workspace roster to track coverage and workload.</p></div></section></div>;
  }

  return (
    <div className="view-padding team-page">
      <section className="team-overview" aria-labelledby="coverage-summary-title">
        <div className="team-overview-heading">
          <div>
            <p className="section-label">Coverage</p>
            <h2 id="coverage-summary-title">Coverage at a glance</h2>
            <p>Availability is set by each teammate or a manager. Workload is counted from the open queue.</p>
          </div>
          <span className="team-live-note"><span aria-hidden="true" />Workload updates with the queue</span>
        </div>
        <dl className="team-summary">
          <div><dt>Available now</dt><dd>{rows.filter((member) => member.availability === "Online").length}<small>of {rows.length} teammates</small></dd></div>
          <div><dt>Assigned cases</dt><dd>{assignedTotal}<small>of {openTickets.length} open</small></dd></div>
          <div className={cn(unassigned > 0 && "team-summary-attention")}><dt>Unassigned</dt><dd>{unassigned}<small>{unassigned ? "need an owner" : "queue covered"}</small></dd></div>
          <div><dt>Team utilisation</dt><dd>{totalCapacity ? `${Math.round((assignedTotal / totalCapacity) * 100)}%` : "0%"}<small>{Math.max(totalCapacity - assignedTotal, 0)} slots available</small></dd></div>
        </dl>
      </section>

      <section className="team-directory" aria-labelledby="team-directory-title">
        <header className="team-directory-header">
          <div><h2 id="team-directory-title">Team directory</h2><p>{rows.length} teammates covering {openTickets.length} open conversations</p></div>
          <label className="team-search"><span className="sr-only">Search team members or coverage</span><Search aria-hidden="true" /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search member or coverage" /></label>
        </header>
        <div className="team-toolbar">
          <div className="team-filter-tabs" aria-label="Filter team by availability">
            {filters.map((filter) => <button key={filter} type="button" className={cn(availability === filter && "is-active")} aria-pressed={availability === filter} onClick={() => setAvailability(filter)}><span>{filter}</span><b>{filterCount(filter)}</b></button>)}
          </div>
          <p aria-live="polite">Showing {visibleMembers.length} of {rows.length}</p>
        </div>

        <div className="team-table-scroll" tabIndex={0} role="region" aria-label="Team coverage table. Scroll horizontally to see all columns on smaller screens.">
          <Table className="team-table" aria-labelledby="team-directory-title">
            <caption className="sr-only">Support team availability, primary coverage, and assigned workload.</caption>
            <TableHeader><TableRow><TableHead>Team member</TableHead><TableHead>Primary coverage</TableHead><TableHead>Workload</TableHead><TableHead>Availability</TableHead><TableHead><span className="sr-only">Actions</span></TableHead></TableRow></TableHeader>
            <TableBody>{visibleMembers.length ? visibleMembers.map((member) => {
              const percentage = Math.min((member.assigned / Math.max(1, member.capacity)) * 100, 100);
              const remaining = member.capacity - member.assigned;
              const editable = isManager || member.name === currentUser?.display_name;
              return <TableRow key={member.id} className={cn("team-row", member.overloaded && "is-overloaded")}>
                <th scope="row" className="team-member-cell"><span className={cn("team-avatar", `team-avatar-${member.tone}`)} aria-hidden="true">{initialsOf(member.name)}</span><span><strong>{member.name}</strong><small>{member.role}</small></span></th>
                <TableCell className="team-coverage-cell"><span className="team-mobile-label">Coverage</span><div className="team-coverage-tags">{member.teams.map((team) => <span key={team}>{team}</span>)}</div></TableCell>
                <TableCell className="team-workload-cell"><span className="team-mobile-label">Workload</span><div className="team-workload-copy"><strong>{member.assigned} <span>/ {member.capacity}</span></strong><small>{member.overloaded ? `${Math.abs(remaining)} over capacity` : remaining === 0 ? "At capacity" : `${remaining} slot${remaining === 1 ? "" : "s"} available`}</small></div><div className="team-capacity-track" aria-label={`${member.name}: ${member.assigned} assigned out of ${member.capacity} capacity`}><span style={{ width: `${percentage}%` }} /></div></TableCell>
                <TableCell className="team-status-cell">{editable
                  ? <Select value={member.availability} onValueChange={(value) => onSetAvailability(member.id, value)}><SelectTrigger aria-label={`Availability for ${member.name}`} className="h-9 min-w-[110px]"><SelectValue /></SelectTrigger><SelectContent>{AVAILABILITY.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select>
                  : <span className={cn("team-status", `team-status-${member.availability.toLowerCase()}`)}><i aria-hidden="true" />{member.availability}</span>}</TableCell>
                <TableCell className="team-action-cell"><Button variant="quiet" size="sm" onClick={() => onFilterQueue(member.name)} aria-label={`Open ${member.name}'s queue`}>Open queue<ChevronRight aria-hidden="true" /></Button></TableCell>
              </TableRow>;
            }) : <TableRow className="team-empty-row"><TableCell colSpan={5}><div><Search aria-hidden="true" /><strong>No teammates match this view</strong><p>Try another name, coverage area, or availability.</p><Button variant="outline" size="sm" onClick={clearFilters}>Clear filters</Button></div></TableCell></TableRow>}</TableBody>
          </Table>
        </div>
      </section>

      <p className="team-footnote">Coverage areas may overlap. Workload counts primary ownership across the current open queue.</p>
    </div>
  );
}
